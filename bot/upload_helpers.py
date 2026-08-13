"""Validation des Shorts et interprétation de leur légende Telegram."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from core.video_processor import _get_video_dimensions, _probe_video


@dataclass(frozen=True)
class UploadRequest:
    publish_at: datetime | None
    title: str


def parse_upload_caption(caption: str | None, now: datetime | None = None) -> UploadRequest:
    """Parse `auto | titre` ou `AAAA-MM-JJ HH:MM | titre`."""
    raw = (caption or "").strip()
    schedule_part, separator, title_part = raw.partition("|")
    schedule_part = schedule_part.strip()
    title = title_part.strip() if separator else ""

    if not schedule_part or schedule_part.lower() == "auto":
        return UploadRequest(None, title or "Mon Short #shorts")

    try:
        local_tz = ZoneInfo(config.TIMEZONE)
        publish_at = datetime.strptime(schedule_part, "%Y-%m-%d %H:%M").replace(tzinfo=local_tz)
    except ValueError as exc:
        raise ValueError(
            "Légende invalide. Utilise `auto | Mon titre` ou "
            "`2026-08-20 17:00 | Mon titre`."
        ) from exc

    current = now or datetime.now(local_tz)
    minimum = current + timedelta(minutes=config.MANUAL_SCHEDULE_MIN_LEAD_MINUTES)
    if publish_at < minimum:
        raise ValueError(
            f"Prévois au moins {config.MANUAL_SCHEDULE_MIN_LEAD_MINUTES} minutes "
            "pour le traitement et l'upload."
        )
    if publish_at > current + timedelta(days=config.MANUAL_SCHEDULE_MAX_DAYS):
        raise ValueError(
            f"La publication ne peut pas dépasser {config.MANUAL_SCHEDULE_MAX_DAYS} jours."
        )
    return UploadRequest(publish_at, title or "Mon Short #shorts")


def validate_uploaded_short(path: Path) -> tuple[float, int, int]:
    """Valide le contenu réel avec ffprobe, indépendamment du MIME Telegram."""
    probe = _probe_video(path)
    duration = float(probe.get("format", {}).get("duration", 0))
    width, height = _get_video_dimensions(probe)
    if duration <= 0:
        raise ValueError("La durée de la vidéo est introuvable.")
    if duration > config.UPLOADED_SHORT_MAX_DURATION_SEC:
        raise ValueError(
            f"Le Short dure {duration:.1f}s. Maximum autorisé : "
            f"{config.UPLOADED_SHORT_MAX_DURATION_SEC}s."
        )
    if width > height:
        raise ValueError(
            f"Format {width}x{height} refusé : envoie une vidéo verticale ou carrée."
        )
    return duration, width, height
