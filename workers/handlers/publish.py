"""Publication d'une vidéo rendue via l'adaptateur social de sa destination."""
import logging
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from api.config import get_settings
from api.database import SessionLocal
from api.integrations.default_publishers import register_default_publishers
from api.integrations.social import (
    PublisherCredentials,
    PublishRequest,
    PublishResult,
    SocialErrorCode,
    SocialPublisherError,
    social_publishers,
)
from api.models import (
    Channel,
    ChannelPlatform,
    ChannelStatus,
    Job,
    JobType,
    MediaAsset,
    Publication,
    PublicationFormat,
    PublicationMediaAsset,
    PublicationStatus,
    PublicationVisibility,
    SocialConnection,
    SocialConnectionStatus,
    Video,
)
from api.security.social_credentials import SocialCredentialCipher
from workers.registry import JobDeferred, registry

logger = logging.getLogger(__name__)

PUBLISHED_PROVIDER_STATUSES = frozenset({
    "published", "publish_complete", "public", "private", "unlisted", "ready",
})
FAILED_PROVIDER_STATUSES = frozenset({
    "failed", "error", "expired", "not_found", "rejected",
})


@dataclass(frozen=True)
class PublishContext:
    publication_id: uuid.UUID
    connection_id: uuid.UUID
    platform: ChannelPlatform
    channel_external_id: str
    storage_keys: tuple[str, ...]
    format: PublicationFormat
    title: str
    description: str | None
    visibility: PublicationVisibility
    scheduled_at: datetime | None
    existing_external_id: str | None


def publish_video(job: Job, heartbeat) -> dict:
    from core.storage_r2 import download_from_r2
    import config

    context = _load_context(job)
    settings = get_settings()
    register_default_publishers(settings)
    publisher = social_publishers.get(context.platform)
    credentials = _load_credentials(context.connection_id, settings.social_credentials_key)
    if _needs_refresh(credentials):
        credentials = _refresh_and_persist(
            publisher, context.connection_id, credentials, settings.social_credentials_key
        )
    if context.existing_external_id:
        _require_lease(heartbeat, "avant la vérification fournisseur", 90)
        provider_status = _call_with_reactive_refresh(
            publisher,
            context.connection_id,
            credentials,
            settings.social_credentials_key,
            lambda creds: publisher.get_status(creds, context.existing_external_id),
        )
        return _persist_reconciliation(context, provider_status)

    work_dir = (
        config.TMP_DIR
        / "workspaces"
        / str(job.workspace_id)
        / "jobs"
        / str(job.id)
    )
    media_paths = tuple(
        work_dir / "publish" / f"{index:02d}-{Path(key).name}"
        for index, key in enumerate(context.storage_keys)
    )
    try:
        _require_lease(heartbeat, "avant le téléchargement du rendu", 10)
        for storage_key, media_path in zip(context.storage_keys, media_paths):
            download_from_r2(storage_key, media_path)
        media_urls: tuple[str, ...] = ()
        if context.platform is ChannelPlatform.INSTAGRAM:
            from core.storage_r2 import create_presigned_download_url

            media_urls = tuple(
                create_presigned_download_url(key, settings.r2_signed_url_ttl_seconds)
                for key in context.storage_keys
            )
        elif context.platform is ChannelPlatform.TIKTOK and context.format in {
            PublicationFormat.PHOTO,
            PublicationFormat.CAROUSEL,
        }:
            media_urls = _tiktok_media_urls(
                context.storage_keys, settings.tiktok_verified_media_base_url
            )
        request = PublishRequest(
            media_path=media_paths[0],
            title=context.title,
            description=context.description,
            visibility=context.visibility,
            scheduled_at=context.scheduled_at,
            media_url=media_urls[0] if media_urls else None,
            format=context.format,
            media_paths=media_paths,
            media_urls=media_urls,
        )
        publisher.validate_media(request)
        _require_lease(heartbeat, "avant l'envoi vers la plateforme", 60)
        result = _call_with_reactive_refresh(
            publisher,
            context.connection_id,
            credentials,
            settings.social_credentials_key,
            lambda creds: publisher.publish(creds, context.channel_external_id, request),
        )
        persisted = _persist_result(context, result)
        if result.status.lower() in {"processing", "pending", "in_progress"}:
            raise JobDeferred("Publication en cours de traitement chez le fournisseur.")
        return persisted
    except JobDeferred:
        raise
    except Exception as exc:
        _persist_failure(context.publication_id, exc)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _refresh_credentials_locked(
    connection_id: uuid.UUID,
    publisher,
    credentials: PublisherCredentials,
    key: str,
) -> PublisherCredentials:
    """Rafraîchit et persiste les credentials sous verrou de la ligne connexion.

    Le verrou (`FOR UPDATE`) sérialise les rafraîchissements concurrents d'une
    même connexion — TikTok fait tourner son refresh token à chaque échange :
    si un concurrent a déjà persisté des credentials à jour, ils sont adoptés
    tels quels au lieu de rejouer l'échange avec des secrets périmés.
    """
    cipher = SocialCredentialCipher(key)
    with SessionLocal() as db:
        connection = db.execute(
            select(SocialConnection)
            .where(SocialConnection.id == connection_id)
            .with_for_update()
        ).scalar_one_or_none()
        if connection is None:
            raise ValueError("La connexion sociale est introuvable.")
        current = PublisherCredentials(
            access_token=cipher.decrypt(connection.access_token_encrypted),
            refresh_token=(
                cipher.decrypt(connection.refresh_token_encrypted)
                if connection.refresh_token_encrypted
                else None
            ),
            scopes=list(connection.scopes or []),
            expires_at=connection.expires_at,
        )
        if current != credentials and not _needs_refresh(current):
            return current
        refreshed = publisher.refresh_credentials(current)
        connection.access_token_encrypted = cipher.encrypt(refreshed.access_token)
        if refreshed.refresh_token:
            connection.refresh_token_encrypted = cipher.encrypt(
                refreshed.refresh_token
            )
        connection.scopes = refreshed.scopes
        connection.expires_at = refreshed.expires_at
        connection.last_verified_at = datetime.now(timezone.utc)
        db.commit()
        return refreshed


def _refresh_and_persist(
    publisher,
    connection_id: uuid.UUID,
    credentials: PublisherCredentials,
    key: str,
) -> PublisherCredentials:
    """Rafraîchit préventivement les credentials sous verrou de ligne.

    Seul un échec d'autorisation met la connexion en quarantaine : une erreur
    transitoire (réseau, saturation fournisseur) laisse la connexion active.
    """
    try:
        return _refresh_credentials_locked(connection_id, publisher, credentials, key)
    except SocialPublisherError as exc:
        if exc.code is SocialErrorCode.AUTHORIZATION:
            _quarantine_connection(connection_id)
        raise


def _call_with_reactive_refresh(
    publisher,
    connection_id: uuid.UUID,
    credentials: PublisherCredentials,
    key: str,
    operation: Callable[[PublisherCredentials], Any],
):
    """Exécute l'appel fournisseur avec un unique rafraîchissement réactif.

    Un refus AUTHORIZATION déclenche un rafraîchissement unique sous verrou de
    ligne, persisté chiffré, puis une seconde et dernière tentative. Si le
    rafraîchissement échoue pour un problème d'autorisation, la connexion est
    mise en quarantaine (EXPIRED + canaux DISCONNECTED) ; dans tous les cas
    l'erreur fournisseur d'origine est relancée telle quelle. Un second refus
    AUTHORIZATION après un rafraîchissement réussi met aussi la connexion en
    quarantaine : le token mort ne doit pas rester ACTIVE.
    """
    try:
        return operation(credentials)
    except SocialPublisherError as exc:
        if exc.code is not SocialErrorCode.AUTHORIZATION:
            raise
        original = exc
    try:
        refreshed = _refresh_credentials_locked(
            connection_id, publisher, credentials, key
        )
    except SocialPublisherError as refresh_exc:
        if refresh_exc.code is SocialErrorCode.AUTHORIZATION:
            _quarantine_connection(connection_id)
        raise original
    except Exception:
        raise original
    try:
        return operation(refreshed)
    except SocialPublisherError as exc:
        if exc.code is SocialErrorCode.AUTHORIZATION:
            _quarantine_connection(connection_id)
        raise


def _quarantine_connection(connection_id: uuid.UUID) -> None:
    """Marque la connexion EXPIRED et ses canaux DISCONNECTED (best-effort)."""
    try:
        with SessionLocal() as db:
            connection = db.get(SocialConnection, connection_id)
            if connection is None or connection.status is not SocialConnectionStatus.ACTIVE:
                return
            connection.status = SocialConnectionStatus.EXPIRED
            for channel in db.scalars(
                select(Channel).where(
                    Channel.connection_id == connection.id,
                    Channel.workspace_id == connection.workspace_id,
                )
            ):
                channel.status = ChannelStatus.DISCONNECTED
            db.commit()
            logger.warning(
                "La connexion sociale %s a été mise en quarantaine : statut EXPIRED "
                "et canaux associés DISCONNECTED après un échec de rafraîchissement.",
                connection_id,
            )
    except Exception:
        logger.warning(
            "Impossible de mettre en quarantaine la connexion sociale %s.",
            connection_id,
            exc_info=True,
        )


def _load_context(job: Job) -> PublishContext:
    raw_publication_id = (job.payload or {}).get("publication_id")
    try:
        publication_id = uuid.UUID(str(raw_publication_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("Le job PUBLISH requiert une publication valide.") from exc
    with SessionLocal() as db:
        row = db.execute(
            select(Publication, Channel, SocialConnection)
            .join(Channel, Channel.id == Publication.channel_id)
            .join(SocialConnection, SocialConnection.id == Channel.connection_id)
            .where(
                Publication.id == publication_id,
                Publication.workspace_id == job.workspace_id,
                Publication.job_id == job.id,
                Channel.workspace_id == job.workspace_id,
                Channel.status == ChannelStatus.ACTIVE,
                SocialConnection.workspace_id == job.workspace_id,
                SocialConnection.platform == Channel.platform,
                SocialConnection.status == SocialConnectionStatus.ACTIVE,
            )
        ).one_or_none()
        if row is None:
            raise ValueError("La publication ou sa connexion est introuvable.")
        publication, channel, connection = row
        if publication.video_id is not None:
            video = db.scalar(select(Video).where(
                Video.id == publication.video_id,
                Video.workspace_id == job.workspace_id,
            ))
            if video is None:
                raise ValueError("La vidéo est introuvable.")
            storage_key = (
                video.storage_key
                if publication.format is PublicationFormat.STANDARD_VIDEO
                else video.rendered_storage_key
            )
            if not storage_key:
                raise ValueError("L'artefact vidéo est introuvable.")
            storage_keys = (storage_key,)
        else:
            storage_keys = tuple(db.scalars(
                select(MediaAsset.storage_key)
                .join(PublicationMediaAsset, PublicationMediaAsset.asset_id == MediaAsset.id)
                .where(
                    PublicationMediaAsset.publication_id == publication.id,
                    MediaAsset.workspace_id == job.workspace_id,
                )
                .order_by(PublicationMediaAsset.position)
            ))
            if not storage_keys:
                raise ValueError("Les images de la publication sont introuvables.")
        if not publication.external_id:
            publication.status = PublicationStatus.PUBLISHING
            publication.error_message = None
            db.commit()
        return PublishContext(
            publication_id=publication.id,
            connection_id=connection.id,
            platform=channel.platform,
            channel_external_id=channel.external_id,
            storage_keys=storage_keys,
            format=publication.format,
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


def _persist_reconciliation(context: PublishContext, provider_status: str) -> dict:
    normalized = provider_status.strip().lower()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        publication = db.get(Publication, context.publication_id)
        if publication is None:
            raise ValueError("La publication est introuvable pendant la réconciliation.")
        response = dict(publication.provider_response or {})
        response["reconciled_status"] = provider_status
        response["reconciled_at"] = now.isoformat()
        publication.provider_response = response
        if normalized in PUBLISHED_PROVIDER_STATUSES:
            publication.status = PublicationStatus.PUBLISHED
            publication.published_at = publication.published_at or now
            publication.error_message = None
        elif normalized in FAILED_PROVIDER_STATUSES:
            publication.status = PublicationStatus.FAILED
            publication.error_message = (
                f"Le fournisseur signale le statut terminal {provider_status}."
            )
        else:
            publication.status = PublicationStatus.PUBLISHING
        db.commit()
    if normalized not in PUBLISHED_PROVIDER_STATUSES | FAILED_PROVIDER_STATUSES:
        raise JobDeferred(
            f"Statut fournisseur encore en cours : {provider_status}.",
        )
    if normalized in FAILED_PROVIDER_STATUSES:
        raise RuntimeError(f"Publication refusée par le fournisseur : {provider_status}.")
    return _result(context.publication_id, context.existing_external_id or "")


def _persist_failure(publication_id: uuid.UUID, exc: Exception) -> None:
    with SessionLocal() as db:
        publication = db.get(Publication, publication_id)
        if publication is not None and not publication.external_id:
            publication.status = PublicationStatus.FAILED
            publication.error_message = str(exc)[:2000]
            db.commit()


def _result(publication_id: uuid.UUID, external_id: str) -> dict:
    return {"publication_id": str(publication_id), "external_id": external_id}


def _require_lease(heartbeat, stage: str, progress: int | None = None) -> None:
    if not heartbeat(progress):
        raise RuntimeError(f"Lease du job perdue {stage}.")


def _tiktok_media_urls(storage_keys: tuple[str, ...], base_url: str) -> tuple[str, ...]:
    base = base_url.strip().rstrip("/")
    if not base.startswith("https://"):
        raise ValueError(
            "TIKTOK_VERIFIED_MEDIA_BASE_URL doit contenir le domaine HTTPS public "
            "vérifié dans TikTok Developer."
        )
    return tuple(f"{base}/{key.lstrip('/')}" for key in storage_keys)


registry.register(JobType.PUBLISH, publish_video)
