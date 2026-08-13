"""Publication d'une vidéo rendue via l'adaptateur social de sa destination."""
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from api.config import get_settings
from api.database import SessionLocal
from api.integrations.social import (
    PublisherCredentials,
    PublishRequest,
    PublishResult,
    social_publishers,
)
from api.integrations.youtube import YouTubePublisher
from api.integrations.tiktok import TikTokPublisher
from api.integrations.facebook import FacebookPublisher
from api.models import (
    Channel,
    ChannelPlatform,
    ChannelStatus,
    Job,
    JobType,
    Publication,
    PublicationStatus,
    PublicationVisibility,
    SocialConnection,
    SocialConnectionStatus,
    Video,
)
from api.security.social_credentials import SocialCredentialCipher
from workers.registry import registry


@dataclass(frozen=True)
class PublishContext:
    publication_id: uuid.UUID
    connection_id: uuid.UUID
    platform: ChannelPlatform
    channel_external_id: str
    storage_key: str
    title: str
    description: str | None
    visibility: PublicationVisibility
    scheduled_at: datetime | None
    existing_external_id: str | None


def publish_video(job: Job, heartbeat) -> dict:
    from core.storage_r2 import download_from_r2
    import config

    context = _load_context(job)
    if context.existing_external_id:
        return _result(context.publication_id, context.existing_external_id)
    settings = get_settings()
    if not social_publishers.has(ChannelPlatform.YOUTUBE):
        social_publishers.register(
            YouTubePublisher(settings.youtube_client_secrets_file)
        )
    if not social_publishers.has(ChannelPlatform.TIKTOK):
        social_publishers.register(TikTokPublisher(
            settings.tiktok_client_key,
            settings.tiktok_client_secret,
            settings.tiktok_sandbox_mode,
        ))
    if not social_publishers.has(ChannelPlatform.FACEBOOK):
        social_publishers.register(FacebookPublisher(
            settings.meta_app_id,
            settings.meta_app_secret,
            settings.meta_graph_api_version,
        ))
    publisher = social_publishers.get(context.platform)
    work_dir = (
        config.TMP_DIR
        / "workspaces"
        / str(job.workspace_id)
        / "jobs"
        / str(job.id)
    )
    media_path = work_dir / "publish" / Path(context.storage_key).name
    try:
        _require_lease(heartbeat, "avant le téléchargement du rendu")
        download_from_r2(context.storage_key, media_path)
        credentials = _load_credentials(context.connection_id, settings.social_credentials_key)
        if _needs_refresh(credentials):
            credentials = publisher.refresh_credentials(credentials)
            _persist_credentials(
                context.connection_id, credentials, settings.social_credentials_key
            )
        request = PublishRequest(
            media_path=media_path,
            title=context.title,
            description=context.description,
            visibility=context.visibility,
            scheduled_at=context.scheduled_at,
        )
        publisher.validate_media(request)
        _require_lease(heartbeat, "avant l'envoi vers la plateforme")
        result = publisher.publish(
            credentials, context.channel_external_id, request
        )
        return _persist_result(context, result)
    except Exception as exc:
        _persist_failure(context.publication_id, exc)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _load_context(job: Job) -> PublishContext:
    raw_publication_id = (job.payload or {}).get("publication_id")
    try:
        publication_id = uuid.UUID(str(raw_publication_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("Le job PUBLISH requiert une publication valide.") from exc
    with SessionLocal() as db:
        row = db.execute(
            select(Publication, Video, Channel, SocialConnection)
            .join(Video, Video.id == Publication.video_id)
            .join(Channel, Channel.id == Publication.channel_id)
            .join(SocialConnection, SocialConnection.id == Channel.connection_id)
            .where(
                Publication.id == publication_id,
                Publication.workspace_id == job.workspace_id,
                Publication.job_id == job.id,
                Video.workspace_id == job.workspace_id,
                Video.id == job.video_id,
                Channel.workspace_id == job.workspace_id,
                Channel.status == ChannelStatus.ACTIVE,
                SocialConnection.workspace_id == job.workspace_id,
                SocialConnection.platform == Channel.platform,
                SocialConnection.status == SocialConnectionStatus.ACTIVE,
            )
        ).one_or_none()
        if row is None:
            raise ValueError("La publication ou sa connexion est introuvable.")
        publication, video, channel, connection = row
        if not video.rendered_storage_key:
            raise ValueError("La vidéo rendue est introuvable.")
        if publication.external_id:
            if publication.scheduled_at:
                publication.status = PublicationStatus.SCHEDULED
            else:
                publication.status = PublicationStatus.PUBLISHED
            db.commit()
        else:
            publication.status = PublicationStatus.PUBLISHING
            publication.error_message = None
            db.commit()
        return PublishContext(
            publication_id=publication.id,
            connection_id=connection.id,
            platform=channel.platform,
            channel_external_id=channel.external_id,
            storage_key=video.rendered_storage_key,
            title=publication.title,
            description=publication.description,
            visibility=publication.visibility,
            scheduled_at=publication.scheduled_at,
            existing_external_id=publication.external_id,
        )


def _load_credentials(connection_id: uuid.UUID, key: str) -> PublisherCredentials:
    cipher = SocialCredentialCipher(key)
    with SessionLocal() as db:
        connection = db.get(SocialConnection, connection_id)
        if connection is None:
            raise ValueError("La connexion sociale est introuvable.")
        return PublisherCredentials(
            access_token=cipher.decrypt(connection.access_token_encrypted),
            refresh_token=(
                cipher.decrypt(connection.refresh_token_encrypted)
                if connection.refresh_token_encrypted
                else None
            ),
            scopes=list(connection.scopes or []),
            expires_at=connection.expires_at,
        )


def _needs_refresh(credentials: PublisherCredentials) -> bool:
    if credentials.expires_at is None:
        return False
    expiry = credentials.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry <= datetime.now(timezone.utc) + timedelta(minutes=5)


def _persist_credentials(
    connection_id: uuid.UUID, credentials: PublisherCredentials, key: str
) -> None:
    cipher = SocialCredentialCipher(key)
    with SessionLocal() as db:
        connection = db.get(SocialConnection, connection_id)
        if connection is None:
            raise ValueError("La connexion sociale est introuvable.")
        connection.access_token_encrypted = cipher.encrypt(credentials.access_token)
        if credentials.refresh_token:
            connection.refresh_token_encrypted = cipher.encrypt(
                credentials.refresh_token
            )
        connection.scopes = credentials.scopes
        connection.expires_at = credentials.expires_at
        connection.last_verified_at = datetime.now(timezone.utc)
        db.commit()


def _persist_result(context: PublishContext, result: PublishResult) -> dict:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        publication = db.get(Publication, context.publication_id)
        if publication is None:
            raise ValueError("La publication est introuvable après l'envoi.")
        publication.external_id = result.external_id
        publication.provider_response = result.raw_response
        publication.error_message = None
        if result.status.lower() in {"processing", "pending", "in_progress"}:
            publication.status = PublicationStatus.PUBLISHING
        elif context.scheduled_at is not None or result.status.lower() == "scheduled":
            publication.status = PublicationStatus.SCHEDULED
        else:
            publication.status = PublicationStatus.PUBLISHED
            publication.published_at = result.published_at or now
        db.commit()
    return _result(context.publication_id, result.external_id)


def _persist_failure(publication_id: uuid.UUID, exc: Exception) -> None:
    with SessionLocal() as db:
        publication = db.get(Publication, publication_id)
        if publication is not None and not publication.external_id:
            publication.status = PublicationStatus.FAILED
            publication.error_message = str(exc)[:2000]
            db.commit()


def _result(publication_id: uuid.UUID, external_id: str) -> dict:
    return {"publication_id": str(publication_id), "external_id": external_id}


def _require_lease(heartbeat, stage: str) -> None:
    if not heartbeat():
        raise RuntimeError(f"Lease du job perdue {stage}.")


registry.register(JobType.PUBLISH, publish_video)
