"""Contrat commun des fournisseurs de publication sociale."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from api.models import ChannelPlatform, PublicationVisibility


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
class PublishRequest:
    media_path: Path
    title: str
    description: str | None
    visibility: PublicationVisibility
    scheduled_at: datetime | None = None


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
    def exchange_code(self, code: str, redirect_uri: str) -> OAuthGrant:
        """Échange le code temporaire et retourne des données normalisées."""

    @abstractmethod
    def list_channels(self) -> list[SocialChannel]:
        """Liste les comptes, chaînes ou Pages accessibles."""

    @abstractmethod
    def validate_media(self, request: PublishRequest) -> None:
        """Lève SocialPublisherError si le média ou les options sont invalides."""

    @abstractmethod
    def publish(self, channel_external_id: str, request: PublishRequest) -> PublishResult:
        """Publie ou programme un média sur une destination."""

    @abstractmethod
    def get_status(self, external_id: str) -> str:
        """Retourne le statut fournisseur courant."""

    @abstractmethod
    def cancel(self, external_id: str) -> None:
        """Annule une publication lorsque le fournisseur le permet."""

    @abstractmethod
    def refresh_credentials(self) -> dict[str, Any]:
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
            raise SocialPublisherError(
                SocialErrorCode.AUTHORIZATION,
                f"La plateforme {platform.value} n'est pas encore connectée.",
            ) from exc


social_publishers = SocialPublisherRegistry()
