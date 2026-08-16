"""Contrat commun des fournisseurs de publication sociale."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from api.models import ChannelPlatform, PublicationFormat, PublicationVisibility


class SocialErrorCode(str, Enum):
    AUTHORIZATION = "authorization"
    VALIDATION = "validation"
    QUOTA = "quota"
    MODERATION = "moderation"
    NETWORK = "network"
    TEMPORARY = "temporary"


class SocialPublisherError(RuntimeError):
    """Erreur fournisseur sûre à persister sans exposer de secret."""

    def __init__(
        self,
        code: SocialErrorCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class PublisherNotRegisteredError(RuntimeError):
    """Adaptateur absent du registre : la plateforme n'est pas configurée côté serveur."""

    def __init__(self, platform: ChannelPlatform) -> None:
        super().__init__(f"La plateforme {platform.value} n'est pas encore configurée.")
        self.platform = platform


@dataclass(frozen=True)
class SocialChannel:
    external_id: str
    name: str
    handle: str | None = None
    avatar_url: str | None = None


@dataclass(frozen=True)
class OAuthGrant:
    provider_account_id: str
    access_token: str
    refresh_token: str | None
    scopes: list[str]
    expires_at: datetime | None
    channels: list[SocialChannel]
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublisherCredentials:
    access_token: str
    refresh_token: str | None
    scopes: list[str]
    expires_at: datetime | None


@dataclass(frozen=True)
class PublishRequest:
    media_path: Path
    title: str
    description: str | None
    visibility: PublicationVisibility
    scheduled_at: datetime | None = None
    media_url: str | None = None
    format: PublicationFormat = PublicationFormat.SHORT_VIDEO
    media_paths: tuple[Path, ...] = ()
    media_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class PublishResult:
    external_id: str
    status: str
    published_at: datetime | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


class SocialPublisher(ABC):
    """Interface sans stockage : les credentials restent à la charge de l'appelant."""

    platform: ChannelPlatform

    @abstractmethod
    def connect(self, state: str, redirect_uri: str) -> str:
        """Retourne l'URL OAuth du fournisseur."""

    @abstractmethod
    def exchange_code(self, code: str, redirect_uri: str) -> list[OAuthGrant]:
        """Échange le code et retourne un grant indépendant par compte distant."""

    @abstractmethod
    def list_channels(self, credentials: PublisherCredentials) -> list[SocialChannel]:
        """Liste les comptes, chaînes ou Pages accessibles."""

    @abstractmethod
    def validate_media(self, request: PublishRequest) -> None:
        """Lève SocialPublisherError si le média ou les options sont invalides."""

    @abstractmethod
    def publish(
        self,
        credentials: PublisherCredentials,
        channel_external_id: str,
        request: PublishRequest,
    ) -> PublishResult:
        """Publie ou programme un média sur une destination."""

    @abstractmethod
    def get_status(self, credentials: PublisherCredentials, external_id: str) -> str:
        """Retourne le statut fournisseur courant."""

    @abstractmethod
    def cancel(self, credentials: PublisherCredentials, external_id: str) -> None:
        """Annule une publication lorsque le fournisseur le permet."""

    @abstractmethod
    def refresh_credentials(
        self, credentials: PublisherCredentials
    ) -> PublisherCredentials:
        """Rafraîchit les credentials sans les journaliser."""


class SocialPublisherRegistry:
    def __init__(self) -> None:
        self._publishers: dict[ChannelPlatform, SocialPublisher] = {}

    def register(self, publisher: SocialPublisher) -> None:
        if publisher.platform in self._publishers:
            raise ValueError(f"Adaptateur {publisher.platform.value} déjà enregistré.")
        self._publishers[publisher.platform] = publisher

    def get(self, platform: ChannelPlatform) -> SocialPublisher:
        try:
            return self._publishers[platform]
        except KeyError as exc:
            raise PublisherNotRegisteredError(platform) from exc

    def has(self, platform: ChannelPlatform) -> bool:
        return platform in self._publishers


social_publishers = SocialPublisherRegistry()
