"""Adaptateur Facebook Reels et photos pour les Pages Meta."""
import json
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
from api.models import ChannelPlatform, PublicationFormat, PublicationVisibility

AUTH_URL = "https://www.facebook.com/dialog/oauth"
SCOPES = ["pages_show_list", "pages_read_engagement", "pages_manage_posts"]
# Codes d'erreur Graph API signalant un token invalide, expiré ou révoqué.
TOKEN_ERROR_CODES = frozenset({190, 102, 10})
TOKEN_ERROR_SUBCODES = frozenset({33})
# Codes d'erreur Graph API signalant une saturation côté Meta.
RATE_LIMIT_ERROR_CODES = frozenset({4, 17, 32, 613})
ACCOUNTS_PAGE_SIZE = 100


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
        short_token = self._request(
            "GET",
            "/oauth/access_token",
            params={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )["access_token"]
        user_token = self._exchange_long_lived_token(short_token)["access_token"]
        pages = self._list_accounts(user_token)
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

    def _exchange_long_lived_token(self, token: str) -> dict:
        """Échange un token contre sa version longue durée (réponse Graph complète)."""
        data = self._request(
            "GET",
            "/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": token,
            },
        )
        if not data.get("access_token"):
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Meta n'a pas retourné de token longue durée.",
            )
        return data

    def _list_accounts(self, access_token: str) -> list[dict]:
        """Parcourt `/me/accounts` en suivant les curseurs, sans doublon de Page."""
        accounts: list[dict] = []
        seen_pages: set[str] = set()
        seen_cursors: set[str] = set()
        after: str | None = None
        while True:
            params = {"fields": "id,name,access_token,picture", "limit": ACCOUNTS_PAGE_SIZE}
            if after:
                params["after"] = after
            payload = self._request("GET", "/me/accounts", access_token, params=params)
            for page in payload.get("data", []):
                page_id = page.get("id")
                if page_id and page_id not in seen_pages:
                    seen_pages.add(page_id)
                    accounts.append(page)
            paging = payload.get("paging") or {}
            after = (paging.get("cursors") or {}).get("after")
            if (
                not paging.get("next")
                or not after
                or not payload.get("data")
                or after in seen_cursors
            ):
                return accounts
            seen_cursors.add(after)

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
        paths = request.media_paths or (request.media_path,)
        if request.format in {PublicationFormat.PHOTO, PublicationFormat.CAROUSEL}:
            invalid_count = (
                request.format is PublicationFormat.PHOTO and len(paths) != 1
            ) or (
                request.format is PublicationFormat.CAROUSEL and not 2 <= len(paths) <= 10
            )
            if invalid_count:
                raise SocialPublisherError(SocialErrorCode.VALIDATION, "Facebook attend une photo ou un carrousel de 2 à 10 images.")
            if any(not path.is_file() or path.suffix.lower() not in {".jpg", ".png"} for path in paths):
                raise SocialPublisherError(SocialErrorCode.VALIDATION, "Facebook attend des images JPEG ou PNG.")
        elif not request.media_path.is_file() or request.media_path.suffix.lower() not in {
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
        if request.format in {PublicationFormat.PHOTO, PublicationFormat.CAROUSEL}:
            return self._publish_images(credentials, channel_external_id, request)
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

    def _publish_images(self, credentials, channel_external_id, request):
        paths = request.media_paths or (request.media_path,)
        caption = request.description or request.title
        if request.format is PublicationFormat.PHOTO:
            with paths[0].open("rb") as image:
                payload = self._request(
                    "POST", f"/{channel_external_id}/photos", credentials.access_token,
                    params={"message": caption, "published": "true"},
                    files={"source": (paths[0].name, image)},
                )
            external_id = payload.get("post_id") or payload["id"]
            return PublishResult(external_id, "published", published_at=datetime.now(timezone.utc), raw_response=payload)
        photo_ids = []
        for path in paths:
            with path.open("rb") as image:
                photo_ids.append(self._request(
                    "POST", f"/{channel_external_id}/photos", credentials.access_token,
                    params={"published": "false"}, files={"source": (path.name, image)},
                )["id"])
        payload = self._request(
            "POST", f"/{channel_external_id}/feed", credentials.access_token,
            params={
                "message": caption,
                "attached_media": json.dumps([{"media_fbid": photo_id} for photo_id in photo_ids]),
            },
        )
        return PublishResult(payload["id"], "published", published_at=datetime.now(timezone.utc), raw_response=payload)

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
        data = self._exchange_long_lived_token(credentials.access_token)
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
        if response.status_code < 400 and not payload.get("error"):
            return payload
        error = payload.get("error") or {}
        if not isinstance(error, dict):
            error = {}
        error_code = error.get("code")
        if (
            response.status_code in {401, 403}
            or error_code in TOKEN_ERROR_CODES
            or error.get("error_subcode") in TOKEN_ERROR_SUBCODES
        ):
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                "Meta a refusé l'opération.",
            )
        raise SocialPublisherError(
            SocialErrorCode.TEMPORARY,
            "Meta a refusé l'opération.",
            retryable=response.status_code >= 429 or error_code in RATE_LIMIT_ERROR_CODES,
        )
