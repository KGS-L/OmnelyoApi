"""Adaptateur Instagram Reels pour comptes professionnels liés à une Page."""
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

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

AUTH_URL = "https://www.facebook.com/dialog/oauth"
SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_content_publish",
]


class InstagramPublisher(SocialPublisher):
    platform = ChannelPlatform.INSTAGRAM

    def __init__(self, app_id: str, app_secret: str, api_version: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.api_version = api_version.strip().lstrip("v")

    @property
    def graph_url(self) -> str:
        return f"https://graph.facebook.com/v{self.api_version}"

    def _configured(self):
        if not self.app_id or not self.app_secret:
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Les credentials Meta ne sont pas configurés.",
            )

    def connect(self, state: str, redirect_uri: str) -> str:
        self._configured()
        return AUTH_URL + "?" + urlencode(
            {
                "client_id": self.app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": ",".join(SCOPES),
                "response_type": "code",
            }
        )

    def exchange_code(self, code: str, redirect_uri: str) -> list[OAuthGrant]:
        self._configured()
        token = self._request(
            "GET",
            "/oauth/access_token",
            params={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )["access_token"]
        pages = self._request(
            "GET",
            "/me/accounts",
            token,
            params={
                "fields": (
                    "id,name,access_token,"
                    "instagram_business_account{id,username,name,profile_picture_url}"
                )
            },
        ).get("data", [])
        grants = []
        for page in pages:
            account = page.get("instagram_business_account")
            if not account or not page.get("access_token"):
                continue
            grants.append(
                OAuthGrant(
                    provider_account_id=account["id"],
                    access_token=page["access_token"],
                    refresh_token=None,
                    scopes=SCOPES,
                    expires_at=None,
                    channels=[
                        SocialChannel(
                            external_id=account["id"],
                            name=account.get("name") or account.get("username") or "Instagram",
                            handle=account.get("username"),
                            avatar_url=account.get("profile_picture_url"),
                        )
                    ],
                    provider_metadata={"facebook_page_id": page["id"]},
                )
            )
        return grants

    def list_channels(self, credentials: PublisherCredentials) -> list[SocialChannel]:
        raise SocialPublisherError(
            SocialErrorCode.AUTHORIZATION,
            "Reconnectez Meta pour actualiser les comptes Instagram accessibles.",
        )

    def validate_media(self, request: PublishRequest) -> None:
        if not request.media_path.is_file() or request.media_path.suffix.lower() not in {
            ".mp4",
            ".mov",
        }:
            raise SocialPublisherError(
                SocialErrorCode.VALIDATION, "Instagram attend un Reel MP4 ou MOV."
            )
        if not request.media_url or not request.media_url.startswith("https://"):
            raise SocialPublisherError(
                SocialErrorCode.VALIDATION,
                "Instagram requiert une URL HTTPS temporaire pour le Reel.",
            )
        if request.scheduled_at is not None:
            raise SocialPublisherError(
                SocialErrorCode.VALIDATION,
                "Instagram Reels ne prend pas en charge cette programmation différée.",
            )
        if request.visibility is not PublicationVisibility.PUBLIC:
            raise SocialPublisherError(
                SocialErrorCode.VALIDATION,
                "Un Reel Instagram doit viser la visibilité publique.",
            )

    def publish(self, credentials, channel_external_id, request):
        self.validate_media(request)
        container_id = self._request(
            "POST",
            f"/{channel_external_id}/media",
            credentials.access_token,
            params={
                "media_type": "REELS",
                "video_url": request.media_url,
                "caption": request.description or request.title,
                "share_to_feed": "true",
            },
        )["id"]
        for _ in range(20):
            status = self._request(
                "GET",
                f"/{container_id}",
                credentials.access_token,
                params={"fields": "status_code"},
            ).get("status_code")
            if status == "FINISHED":
                break
            if status in {"ERROR", "EXPIRED"}:
                raise SocialPublisherError(
                    SocialErrorCode.VALIDATION,
                    "Instagram a rejeté le conteneur Reel.",
                )
            time.sleep(3)
        else:
            raise SocialPublisherError(
                SocialErrorCode.TEMPORARY,
                "Le traitement Instagram du Reel est encore en cours.",
                retryable=True,
            )
        media_id = self._request(
            "POST",
            f"/{channel_external_id}/media_publish",
            credentials.access_token,
            params={"creation_id": container_id},
        )["id"]
        return PublishResult(
            media_id,
            "published",
            published_at=datetime.now(timezone.utc),
            raw_response={"media_id": media_id, "container_id": container_id},
        )

    def get_status(self, credentials, external_id):
        payload = self._request(
            "GET",
            f"/{external_id}",
            credentials.access_token,
            params={"fields": "id,media_type,permalink"},
        )
        return "published" if payload.get("id") else "not_found"

    def cancel(self, credentials, external_id):
        raise SocialPublisherError(
            SocialErrorCode.VALIDATION,
            "Instagram ne permet pas d'annuler un Reel déjà publié via ce flux.",
        )

    def refresh_credentials(self, credentials):
        data = self._request(
            "GET",
            "/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": credentials.access_token,
            },
        )
        return PublisherCredentials(
            data["access_token"],
            None,
            credentials.scopes,
            datetime.now(timezone.utc)
            + timedelta(seconds=data.get("expires_in", 5_184_000)),
        )

    def _request(self, method, path, access_token=None, **kwargs):
        params = kwargs.pop("params", {})
        if access_token:
            params["access_token"] = access_token
        try:
            response = requests.request(
                method, self.graph_url + path, params=params, timeout=30, **kwargs
            )
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SocialPublisherError(
                SocialErrorCode.NETWORK, "Meta est inaccessible.", retryable=True
            ) from exc
        if response.status_code >= 400 or payload.get("error"):
            error = payload.get("error", {})
            code = (
                SocialErrorCode.AUTHORIZATION
                if response.status_code in {401, 403} or error.get("code") in {190, 200}
                else SocialErrorCode.TEMPORARY
            )
            raise SocialPublisherError(
                code,
                "Instagram a refusé l'opération.",
                retryable=response.status_code >= 429,
            )
        return payload
