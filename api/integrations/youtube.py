"""Adaptateur YouTube OAuth et Data API sans token utilisateur global."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.integrations.social import (
    OAuthGrant,
    PublisherCredentials,
    PublishRequest,
    PublishResult,
    SocialChannel,
    SocialErrorCode,
    SocialPublisher,
    SocialPublisherError,
)
from api.models import ChannelPlatform, PublicationVisibility

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.upload",
]
MAX_UPLOAD_BYTES = 256 * 1024**3


class YouTubePublisher(SocialPublisher):
    platform = ChannelPlatform.YOUTUBE

    def __init__(self, client_secrets_file: Path) -> None:
        self.client_secrets_file = client_secrets_file

    def _flow(self, redirect_uri: str):
        try:
            from google_auth_oauthlib.flow import Flow
        except ImportError as exc:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Le connecteur OAuth YouTube n'est pas installé.",
            ) from exc
        if not self.client_secrets_file.is_file():
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Les credentials OAuth YouTube ne sont pas configurés.",
            )
        try:
            return Flow.from_client_secrets_file(
                str(self.client_secrets_file),
                scopes=YOUTUBE_SCOPES,
                redirect_uri=redirect_uri,
            )
        except (OSError, ValueError) as exc:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Le fichier OAuth YouTube est invalide.",
            ) from exc

    def connect(self, state: str, redirect_uri: str) -> str:
        url, _ = self._flow(redirect_uri).authorization_url(
            state=state,
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return url

    def exchange_code(self, code: str, redirect_uri: str) -> OAuthGrant:
        flow = self._flow(redirect_uri)
        try:
            flow.fetch_token(code=code)
            credentials = flow.credentials
            normalized = self._normalize(credentials)
            channels = self.list_channels(normalized)
        except SocialPublisherError:
            raise
        except Exception as exc:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "YouTube a refusé l'authentification OAuth.",
            ) from exc
        if not channels:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Aucune chaîne YouTube accessible n'a été trouvée.",
            )
        return OAuthGrant(
            provider_account_id=channels[0].external_id,
            access_token=normalized.access_token,
            refresh_token=normalized.refresh_token,
            scopes=normalized.scopes,
            expires_at=normalized.expires_at,
            channels=channels,
        )

    def list_channels(self, credentials: PublisherCredentials) -> list[SocialChannel]:
        try:
            response = self._service(credentials).channels().list(
                part="id,snippet", mine=True
            ).execute()
        except Exception as exc:
            raise _translate_google_error(exc) from exc
        return [
            SocialChannel(
                external_id=item["id"],
                name=item["snippet"]["title"],
                handle=item["snippet"].get("customUrl"),
                avatar_url=_thumbnail(item["snippet"].get("thumbnails", {})),
            )
            for item in response.get("items", [])
        ]

    def validate_media(self, request: PublishRequest) -> None:
        if not request.media_path.is_file():
            raise SocialPublisherError(
                SocialErrorCode.VALIDATION, "Le fichier vidéo est introuvable."
            )
        if request.media_path.suffix.lower() not in {".mp4", ".mov"}:
            raise SocialPublisherError(
                SocialErrorCode.VALIDATION, "YouTube attend une vidéo MP4 ou MOV."
            )
        if request.media_path.stat().st_size > MAX_UPLOAD_BYTES:
            raise SocialPublisherError(
                SocialErrorCode.VALIDATION, "La vidéo dépasse la limite YouTube."
            )
        if request.scheduled_at is not None:
            if request.scheduled_at.utcoffset() is None:
                raise SocialPublisherError(
                    SocialErrorCode.VALIDATION,
                    "La programmation YouTube requiert un fuseau horaire.",
                )
            if request.scheduled_at <= datetime.now(timezone.utc):
                raise SocialPublisherError(
                    SocialErrorCode.VALIDATION,
                    "La programmation YouTube doit être dans le futur.",
                )
            if request.visibility is not PublicationVisibility.PUBLIC:
                raise SocialPublisherError(
                    SocialErrorCode.VALIDATION,
                    "Une vidéo YouTube programmée doit viser la visibilité publique.",
                )

    def publish(
        self,
        credentials: PublisherCredentials,
        channel_external_id: str,
        request: PublishRequest,
    ) -> PublishResult:
        self.validate_media(request)
        if channel_external_id not in {
            channel.external_id for channel in self.list_channels(credentials)
        }:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "La chaîne YouTube ne correspond pas à cette connexion.",
            )
        status_body = {
            "privacyStatus": request.visibility.value,
            "selfDeclaredMadeForKids": False,
        }
        result_status = request.visibility.value
        if request.scheduled_at is not None:
            status_body["privacyStatus"] = "private"
            status_body["publishAt"] = request.scheduled_at.astimezone(
                timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            result_status = "scheduled"
        body = {
            "snippet": {
                "title": request.title,
                "description": request.description or "",
                "categoryId": "22",
            },
            "status": status_body,
        }
        try:
            from googleapiclient.http import MediaFileUpload

            operation = self._service(credentials).videos().insert(
                part="snippet,status",
                body=body,
                media_body=MediaFileUpload(
                    str(request.media_path), mimetype="video/*", resumable=True
                ),
            )
            response = None
            while response is None:
                _, response = operation.next_chunk()
        except SocialPublisherError:
            raise
        except Exception as exc:
            raise _translate_google_error(exc) from exc
        return PublishResult(
            external_id=response["id"],
            status=result_status,
            raw_response={"id": response["id"]},
        )

    def get_status(self, credentials: PublisherCredentials, external_id: str) -> str:
        try:
            response = self._service(credentials).videos().list(
                part="status", id=external_id
            ).execute()
        except Exception as exc:
            raise _translate_google_error(exc) from exc
        items = response.get("items", [])
        return items[0]["status"]["privacyStatus"] if items else "not_found"

    def cancel(self, credentials: PublisherCredentials, external_id: str) -> None:
        try:
            self._service(credentials).videos().delete(id=external_id).execute()
        except Exception as exc:
            raise _translate_google_error(exc) from exc

    def refresh_credentials(
        self, credentials: PublisherCredentials
    ) -> PublisherCredentials:
        google_credentials = self._google_credentials(credentials)
        if not google_credentials.refresh_token:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "La connexion YouTube doit être renouvelée.",
            )
        try:
            from google.auth.transport.requests import Request as GoogleAuthRequest

            google_credentials.refresh(GoogleAuthRequest())
        except Exception as exc:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Le token YouTube n'a pas pu être rafraîchi.",
            ) from exc
        return self._normalize(google_credentials)

    def _service(self, credentials: PublisherCredentials):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Le connecteur YouTube Data API n'est pas installé.",
            ) from exc
        return build(
            "youtube",
            "v3",
            credentials=self._google_credentials(credentials),
            cache_discovery=False,
        )

    def _google_credentials(self, credentials: PublisherCredentials):
        try:
            from google.oauth2.credentials import Credentials
        except ImportError as exc:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Le connecteur Google OAuth n'est pas installé.",
            ) from exc
        config = self._client_config()
        return Credentials(
            token=credentials.access_token,
            refresh_token=credentials.refresh_token,
            token_uri=config["token_uri"],
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            scopes=credentials.scopes,
            expiry=credentials.expires_at,
        )

    def _client_config(self) -> dict:
        import json

        try:
            payload = json.loads(self.client_secrets_file.read_text())
            return payload.get("web") or payload["installed"]
        except (OSError, KeyError, ValueError, TypeError) as exc:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Le fichier OAuth YouTube est invalide.",
            ) from exc

    @staticmethod
    def _normalize(credentials: Any) -> PublisherCredentials:
        return PublisherCredentials(
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            scopes=list(credentials.scopes or YOUTUBE_SCOPES),
            expires_at=credentials.expiry,
        )


def _thumbnail(thumbnails: dict) -> str | None:
    for size in ("high", "medium", "default"):
        if thumbnails.get(size, {}).get("url"):
            return thumbnails[size]["url"]
    return None


def _youtube_error(exc: Any) -> SocialPublisherError:
    status = getattr(exc.resp, "status", None)
    if status in {401, 403}:
        code = SocialErrorCode.AUTHORIZATION if status == 401 else SocialErrorCode.QUOTA
        return SocialPublisherError(code, "YouTube a refusé cette opération.")
    if status == 429:
        return SocialPublisherError(
            SocialErrorCode.QUOTA, "Le quota YouTube est temporairement atteint.", retryable=True
        )
    if status is not None and status >= 500:
        return SocialPublisherError(
            SocialErrorCode.TEMPORARY, "YouTube est temporairement indisponible.", retryable=True
        )
    return SocialPublisherError(SocialErrorCode.VALIDATION, "YouTube a rejeté la requête.")


def _translate_google_error(exc: Exception) -> SocialPublisherError:
    if isinstance(exc, SocialPublisherError):
        return exc
    if hasattr(exc, "resp"):
        return _youtube_error(exc)
    return SocialPublisherError(
        SocialErrorCode.NETWORK,
        "La communication avec YouTube a échoué.",
        retryable=True,
    )
