"""Adaptateur TikTok Content Posting API en mode sandbox/non audité."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

from api.integrations.social import (
    OAuthGrant, PublisherCredentials, PublishRequest, PublishResult, SocialChannel,
    SocialErrorCode, SocialPublisher, SocialPublisherError,
)
from api.models import ChannelPlatform, PublicationFormat, PublicationVisibility

API_BASE = "https://open.tiktokapis.com"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
SCOPES = ["user.info.basic", "video.publish", "video.upload"]


class TikTokPublisher(SocialPublisher):
    platform = ChannelPlatform.TIKTOK

    def __init__(self, client_key: str, client_secret: str, sandbox_mode: bool = True):
        self.client_key = client_key
        self.client_secret = client_secret
        self.sandbox_mode = sandbox_mode

    def _configured(self) -> None:
        if not self.client_key or not self.client_secret:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Les credentials TikTok ne sont pas configurés.",
            )

    def connect(self, state: str, redirect_uri: str) -> str:
        self._configured()
        return AUTH_URL + "?" + urlencode({
            "client_key": self.client_key, "scope": ",".join(SCOPES),
            "response_type": "code", "redirect_uri": redirect_uri, "state": state,
        })

    def exchange_code(self, code: str, redirect_uri: str) -> list[OAuthGrant]:
        self._configured()
        payload = self._request("POST", "/v2/oauth/token/", data={
            "client_key": self.client_key, "client_secret": self.client_secret,
            "code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri,
        }, authenticated=False)
        credentials = PublisherCredentials(
            payload["access_token"], payload.get("refresh_token"),
            payload.get("scope", "").split(","),
            datetime.now(timezone.utc) + timedelta(seconds=payload["expires_in"]),
        )
        channels = self.list_channels(credentials)
        return [OAuthGrant(
            provider_account_id=payload["open_id"], access_token=credentials.access_token,
            refresh_token=credentials.refresh_token, scopes=credentials.scopes,
            expires_at=credentials.expires_at, channels=channels,
        )]

    def list_channels(self, credentials: PublisherCredentials) -> list[SocialChannel]:
        data = self._request(
            "GET", "/v2/user/info/", credentials,
            params={"fields": "open_id,display_name,avatar_url"},
        )["data"]["user"]
        return [SocialChannel(data["open_id"], data.get("display_name") or "TikTok", avatar_url=data.get("avatar_url"))]

    def validate_media(self, request: PublishRequest) -> None:
        paths = request.media_paths or (request.media_path,)
        if request.format in {PublicationFormat.PHOTO, PublicationFormat.CAROUSEL}:
            if not 1 <= len(paths) <= 35:
                raise SocialPublisherError(SocialErrorCode.VALIDATION, "TikTok accepte entre 1 et 35 images.")
            if any(not path.is_file() or path.suffix.lower() not in {".jpg", ".png"} for path in paths):
                raise SocialPublisherError(SocialErrorCode.VALIDATION, "TikTok attend des images JPEG ou PNG.")
            if len(request.media_urls) != len(paths) or any(not url.startswith("https://") for url in request.media_urls):
                raise SocialPublisherError(SocialErrorCode.VALIDATION, "TikTok requiert une URL HTTPS pour chaque image.")
        elif not request.media_path.is_file() or request.media_path.suffix.lower() not in {".mp4", ".mov", ".webm"}:
            raise SocialPublisherError(SocialErrorCode.VALIDATION, "TikTok attend une vidéo MP4, MOV ou WebM.")
        if request.format in {PublicationFormat.SHORT_VIDEO, PublicationFormat.STANDARD_VIDEO} and request.media_path.stat().st_size > 64 * 1024**2:
            raise SocialPublisherError(SocialErrorCode.VALIDATION, "Le mode d'upload TikTok initial est limité à 64 Mo.")
        if request.scheduled_at is not None:
            raise SocialPublisherError(SocialErrorCode.VALIDATION, "TikTok ne prend pas en charge la programmation différée.")
        if self.sandbox_mode and request.visibility is not PublicationVisibility.PRIVATE:
            raise SocialPublisherError(SocialErrorCode.VALIDATION, "TikTok sandbox autorise uniquement SELF_ONLY.")

    def publish(self, credentials, channel_external_id, request):
        self.validate_media(request)
        if request.format in {PublicationFormat.PHOTO, PublicationFormat.CAROUSEL}:
            data = self._request("POST", "/v2/post/publish/content/init/", credentials, json={
                "post_info": {
                    "title": request.description or request.title,
                    "privacy_level": "SELF_ONLY",
                    "disable_comment": False,
                    "auto_add_music": True,
                },
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "photo_cover_index": 0,
                    "photo_images": list(request.media_urls),
                },
                "post_mode": "DIRECT_POST",
                "media_type": "PHOTO",
            })["data"]
            return PublishResult(data["publish_id"], "processing", raw_response={"publish_id": data["publish_id"]})
        size = request.media_path.stat().st_size
        init = self._request("POST", "/v2/post/publish/video/init/", credentials, json={
            "post_info": {"title": request.description or request.title, "privacy_level": "SELF_ONLY",
                          "disable_duet": False, "disable_comment": False, "disable_stitch": False},
            "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                            "chunk_size": size, "total_chunk_count": 1},
        })["data"]
        with request.media_path.open("rb") as media:
            response = requests.put(init["upload_url"], data=media, headers={
                "Content-Type": _mime(request.media_path), "Content-Length": str(size),
                "Content-Range": f"bytes 0-{size - 1}/{size}",
            }, timeout=300)
        if response.status_code not in {200, 201, 206}:
            raise SocialPublisherError(SocialErrorCode.NETWORK, "L'upload TikTok a échoué.", retryable=True)
        return PublishResult(init["publish_id"], "processing", raw_response={"publish_id": init["publish_id"]})

    def get_status(self, credentials, external_id):
        return self._request("POST", "/v2/post/publish/status/fetch/", credentials,
                             json={"publish_id": external_id})["data"]["status"]

    def cancel(self, credentials, external_id):
        self._request("POST", "/v2/post/publish/cancel/", credentials, json={"publish_id": external_id})

    def refresh_credentials(self, credentials):
        if not credentials.refresh_token:
            raise SocialPublisherError(SocialErrorCode.AUTHORIZATION, "La connexion TikTok doit être renouvelée.")
        data = self._request("POST", "/v2/oauth/token/", data={
            "client_key": self.client_key, "client_secret": self.client_secret,
            "grant_type": "refresh_token", "refresh_token": credentials.refresh_token,
        }, authenticated=False)
        return PublisherCredentials(data["access_token"], data.get("refresh_token", credentials.refresh_token),
                                    data.get("scope", "").split(","),
                                    datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"]))

    def _request(self, method, path, credentials=None, authenticated=True, **kwargs):
        headers = kwargs.pop("headers", {})
        if authenticated:
            headers["Authorization"] = f"Bearer {credentials.access_token}"
        try:
            response = requests.request(method, API_BASE + path, headers=headers, timeout=30, **kwargs)
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SocialPublisherError(SocialErrorCode.NETWORK, "TikTok est inaccessible.", retryable=True) from exc
        error = payload.get("error") or {}
        if isinstance(error, str):
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "TikTok a refusé l'authentification.",
            )
        if response.status_code >= 400 or error.get("code") not in {None, "ok"}:
            code = SocialErrorCode.AUTHORIZATION if response.status_code in {401, 403} else SocialErrorCode.TEMPORARY
            raise SocialPublisherError(code, "TikTok a refusé l'opération.", retryable=response.status_code >= 429)
        return payload


def _mime(path: Path) -> str:
    return {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}[path.suffix.lower()]
