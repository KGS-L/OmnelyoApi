"""Adaptateur Facebook Reels Publishing pour les Pages Meta."""
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
SCOPES = ["pages_show_list", "pages_read_engagement", "pages_manage_posts"]


class FacebookPublisher(SocialPublisher):
    platform = ChannelPlatform.FACEBOOK

    def __init__(self, app_id: str, app_secret: str, api_version: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.api_version = api_version.strip().lstrip("v")

    @property
    def graph_url(self) -> str:
        return f"https://graph.facebook.com/v{self.api_version}"

    def _configured(self) -> None:
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
        )
        user_token = token["access_token"]
        pages = self._request(
            "GET",
            "/me/accounts",
            access_token=user_token,
            params={"fields": "id,name,access_token,picture"},
        ).get("data", [])
        return [
            OAuthGrant(
                provider_account_id=page["id"],
                access_token=page["access_token"],
                refresh_token=None,
                scopes=SCOPES,
                expires_at=None,
                channels=[
                    SocialChannel(
                        external_id=page["id"],
                        name=page["name"],
                        avatar_url=(page.get("picture", {}).get("data", {}).get("url")),
                    )
                ],
            )
            for page in pages
            if page.get("id") and page.get("access_token")
        ]

    def list_channels(self, credentials: PublisherCredentials) -> list[SocialChannel]:
        page = self._request(
            "GET", "/me", credentials.access_token, params={"fields": "id,name,picture"}
        )
        return [
            SocialChannel(
                page["id"],
                page["name"],
                avatar_url=page.get("picture", {}).get("data", {}).get("url"),
            )
        ]

    def validate_media(self, request: PublishRequest) -> None:
        if not request.media_path.is_file() or request.media_path.suffix.lower() not in {
            ".mp4",
            ".mov",
        }:
            raise SocialPublisherError(
                SocialErrorCode.VALIDATION, "Facebook attend un Reel MP4 ou MOV."
            )
        if request.scheduled_at is not None:
            raise SocialPublisherError(
                SocialErrorCode.VALIDATION,
                "La programmation Facebook Reels n'est pas encore activée.",
            )
        if request.visibility is not PublicationVisibility.PUBLIC:
            raise SocialPublisherError(
                SocialErrorCode.VALIDATION,
                "Un Reel Facebook doit viser la visibilité publique.",
            )

    def publish(self, credentials, channel_external_id, request):
        self.validate_media(request)
        start = self._request(
            "POST",
            f"/{channel_external_id}/video_reels",
            credentials.access_token,
            params={"upload_phase": "start"},
        )
        video_id = start["video_id"]
        with request.media_path.open("rb") as media:
            try:
                uploaded = requests.post(
                    start["upload_url"],
                    headers={
                        "Authorization": f"OAuth {credentials.access_token}",
                        "offset": "0",
                        "file_size": str(request.media_path.stat().st_size),
                    },
                    data=media,
                    timeout=300,
                )
                uploaded.raise_for_status()
            except requests.RequestException as exc:
                raise SocialPublisherError(
                    SocialErrorCode.NETWORK,
                    "L'upload Facebook a échoué.",
                    retryable=True,
                ) from exc
        finished = self._request(
            "POST",
            f"/{channel_external_id}/video_reels",
            credentials.access_token,
            params={
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "title": request.title,
                "description": request.description or "",
            },
        )
        return PublishResult(
            video_id,
            "processing",
            raw_response={"video_id": video_id, "success": finished.get("success")},
        )

    def get_status(self, credentials, external_id):
        payload = self._request(
            "GET",
            f"/{external_id}",
            credentials.access_token,
            params={"fields": "status"},
        )
        return payload.get("status", {}).get("video_status", "unknown")

    def cancel(self, credentials, external_id):
        self._request("DELETE", f"/{external_id}", credentials.access_token)

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
                method,
                self.graph_url + path,
                params=params,
                timeout=30,
                **kwargs,
            )
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise SocialPublisherError(
                SocialErrorCode.NETWORK,
                "Meta est inaccessible.",
                retryable=True,
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
                "Meta a refusé l'opération.",
                retryable=response.status_code >= 429,
            )
        return payload
