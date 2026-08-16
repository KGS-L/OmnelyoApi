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
from api.models import ChannelPlatform, PublicationFormat, PublicationVisibility

AUTH_URL = "https://www.facebook.com/dialog/oauth"
SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "instagram_basic",
    "instagram_content_publish",
]
IG_ACCOUNT_FIELDS = "instagram_business_account{id,username,name,profile_picture_url}"
# Codes d'erreur Graph API signalant un token invalide, expiré ou révoqué.
TOKEN_ERROR_CODES = frozenset({190, 102, 10})
TOKEN_ERROR_SUBCODES = frozenset({33})
# Codes d'erreur Graph API signalant une saturation côté Meta.
RATE_LIMIT_ERROR_CODES = frozenset({4, 17, 32, 613})
ACCOUNTS_PAGE_SIZE = 100


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
            params = {"fields": f"id,name,access_token,{IG_ACCOUNT_FIELDS}", "limit": ACCOUNTS_PAGE_SIZE}
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
            "GET",
            "/me",
            credentials.access_token,
            params={"fields": f"id,name,picture,{IG_ACCOUNT_FIELDS}"},
        )
        account = page.get("instagram_business_account") or {}
        account_id = account.get("id")
        if not account_id:
            return []
        return [
            SocialChannel(
                external_id=account_id,
                name=account.get("name") or account.get("username") or "Instagram",
                handle=account.get("username"),
                avatar_url=account.get("profile_picture_url"),
            )
        ]

    def validate_media(self, request: PublishRequest) -> None:
        paths = request.media_paths or (request.media_path,)
        urls = request.media_urls or ((request.media_url,) if request.media_url else ())
        if request.format in {PublicationFormat.PHOTO, PublicationFormat.CAROUSEL}:
            expected = 1 if request.format is PublicationFormat.PHOTO else None
            if expected == 1 and len(paths) != 1 or request.format is PublicationFormat.CAROUSEL and not 2 <= len(paths) <= 10:
                raise SocialPublisherError(SocialErrorCode.VALIDATION, "Instagram attend une photo ou un carrousel de 2 à 10 images.")
            if any(not path.is_file() or path.suffix.lower() not in {".jpg", ".png"} for path in paths):
                raise SocialPublisherError(SocialErrorCode.VALIDATION, "Instagram attend des images JPEG ou PNG.")
        elif not request.media_path.is_file() or request.media_path.suffix.lower() not in {".mp4", ".mov"}:
            raise SocialPublisherError(
                SocialErrorCode.VALIDATION, "Instagram attend un Reel MP4 ou MOV."
            )
        if len(urls) != len(paths) or any(not url.startswith("https://") for url in urls):
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
        if request.format in {PublicationFormat.PHOTO, PublicationFormat.CAROUSEL}:
            return self._publish_images(credentials, channel_external_id, request)
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

    def _publish_images(self, credentials, channel_external_id, request):
        caption = request.description or request.title
        if request.format is PublicationFormat.PHOTO:
            container_id = self._request(
                "POST", f"/{channel_external_id}/media", credentials.access_token,
                params={"image_url": request.media_urls[0], "caption": caption},
            )["id"]
        else:
            children = [
                self._request(
                    "POST", f"/{channel_external_id}/media", credentials.access_token,
                    params={"image_url": url, "is_carousel_item": "true"},
                )["id"]
                for url in request.media_urls
            ]
            container_id = self._request(
                "POST", f"/{channel_external_id}/media", credentials.access_token,
                params={"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption},
            )["id"]
        media_id = self._request(
            "POST", f"/{channel_external_id}/media_publish", credentials.access_token,
            params={"creation_id": container_id},
        )["id"]
        return PublishResult(
            media_id, "published", published_at=datetime.now(timezone.utc),
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
                SocialErrorCode.NETWORK, "Meta est inaccessible.", retryable=True
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
                "Instagram a refusé l'opération.",
            )
        raise SocialPublisherError(
            SocialErrorCode.TEMPORARY,
            "Instagram a refusé l'opération.",
            retryable=response.status_code >= 429 or error_code in RATE_LIMIT_ERROR_CODES,
        )
