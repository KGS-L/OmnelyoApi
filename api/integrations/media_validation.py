"""Matrice de prévalidation sans téléchargement des médias rendus."""
from datetime import datetime
from pathlib import PurePosixPath

from api.integrations.social import SocialErrorCode, SocialPublisherError
from api.models import ChannelPlatform, PublicationVisibility

YOUTUBE_SHORT_MAX_SECONDS = 180
YOUTUBE_TITLE_MAX_LENGTH = 100
YOUTUBE_DESCRIPTION_MAX_LENGTH = 5000


def validate_publication_preflight(
    *,
    platform: ChannelPlatform,
    storage_key: str,
    duration_seconds: float | None,
    title: str,
    description: str | None,
    visibility: PublicationVisibility,
    scheduled_at: datetime | None,
) -> None:
    if platform is ChannelPlatform.TIKTOK:
        suffix = PurePosixPath(storage_key).suffix.lower()
        if suffix not in {".mp4", ".mov", ".webm"}:
            raise SocialPublisherError(SocialErrorCode.VALIDATION, "TikTok attend un rendu MP4, MOV ou WebM.")
        if duration_seconds is None or duration_seconds <= 0 or duration_seconds > 180:
            raise SocialPublisherError(SocialErrorCode.VALIDATION, "TikTok sandbox accepte ici des vidéos de 3 minutes maximum.")
        if scheduled_at is not None:
            raise SocialPublisherError(SocialErrorCode.VALIDATION, "TikTok ne prend pas en charge la programmation différée.")
        if visibility is not PublicationVisibility.PRIVATE:
            raise SocialPublisherError(SocialErrorCode.VALIDATION, "TikTok sandbox autorise uniquement SELF_ONLY.")
        if len(description or title) > 2200:
            raise SocialPublisherError(SocialErrorCode.VALIDATION, "La légende TikTok ne peut pas dépasser 2 200 caractères.")
        return
    if platform is not ChannelPlatform.YOUTUBE:
        raise SocialPublisherError(
            SocialErrorCode.AUTHORIZATION,
            f"La publication {platform.value} n'est pas encore disponible.",
        )
    suffix = PurePosixPath(storage_key).suffix.lower()
    if suffix not in {".mp4", ".mov"}:
        raise SocialPublisherError(
            SocialErrorCode.VALIDATION,
            "YouTube attend un rendu MP4 ou MOV.",
        )
    if duration_seconds is None or duration_seconds <= 0:
        raise SocialPublisherError(
            SocialErrorCode.VALIDATION,
            "La durée du rendu doit être connue avant publication.",
        )
    if duration_seconds > YOUTUBE_SHORT_MAX_SECONDS:
        raise SocialPublisherError(
            SocialErrorCode.VALIDATION,
            "Un Short YouTube ne peut pas dépasser 3 minutes.",
        )
    if len(title) > YOUTUBE_TITLE_MAX_LENGTH:
        raise SocialPublisherError(
            SocialErrorCode.VALIDATION,
            "Le titre YouTube ne peut pas dépasser 100 caractères.",
        )
    if description and len(description) > YOUTUBE_DESCRIPTION_MAX_LENGTH:
        raise SocialPublisherError(
            SocialErrorCode.VALIDATION,
            "La description YouTube ne peut pas dépasser 5 000 caractères.",
        )
    if scheduled_at is not None and visibility is not PublicationVisibility.PUBLIC:
        raise SocialPublisherError(
            SocialErrorCode.VALIDATION,
            "Une vidéo YouTube programmée doit viser la visibilité publique.",
        )
