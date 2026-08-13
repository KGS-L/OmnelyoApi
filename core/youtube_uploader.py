"""
Upload + programmation des Shorts sur YouTube via l'API Data v3.
Utilise privacyStatus="private" + publishAt pour la publication différée.
"""
import logging
from pathlib import Path
from datetime import datetime, timezone

from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from core.youtube_auth import get_youtube_service

logger = logging.getLogger(__name__)


def upload_scheduled_short(
    video_path: Path,
    title: str,
    description: str,
    publish_at: datetime,
    tags: list[str] | None = None,
    category_id: str = "22",  # "People & Blogs"
    user_id: int | None = None,  # ← NOUVEAU pour multi-user
) -> str:
    """
    Upload `video_path` sur YouTube, programmé pour devenir public à `publish_at`.
    
    Args:
        user_id: Si fourni, utilise le token OAuth de cet utilisateur spécifique
    """
    youtube = get_youtube_service(user_id=user_id)  # ← passe user_id

    if publish_at.tzinfo is None:
        raise ValueError("publish_at doit contenir un fuseau horaire")
    publish_at_utc = publish_at.astimezone(timezone.utc)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "selfDeclaredMadeForKids": False,
        },
    }

    logger.info("Début upload YouTube", extra={"title": title, "publish_at": publish_at.isoformat()})
    
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/*")

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    last_progress = 0
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = status.progress()
            if progress - last_progress > 0.1:  # Log tous les 10%
                logger.info("Upload progress: %.0f%%", progress * 100)
                last_progress = progress

    video_id = response["id"]
    logger.info("Upload terminé", extra={"video_id": video_id})
    
    return video_id


def check_publish_status(youtube_video_id: str, user_id: int | None = None) -> str:
    """
    Interroge l'API pour connaître le privacyStatus actuel.
    """
    youtube = get_youtube_service(user_id=user_id)  # ← passe user_id

    try:
        response = youtube.videos().list(
            part="status",
            id=youtube_video_id,
        ).execute()
    except HttpError as e:
        raise RuntimeError(f"Erreur API YouTube: {e}") from e

    items = response.get("items", [])
    if not items:
        return "not_found"

    return items[0]["status"]["privacyStatus"]


def update_video_thumbnail(video_id: str, thumbnail_path: Path, user_id: int | None = None) -> None:
    """
    Met à jour la miniature d'une vidéo existante.
    """
    youtube = get_youtube_service(user_id=user_id)
    
    media = MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg")
    youtube.thumbnails().set(
        videoId=video_id,
        media_body=media,
    ).execute()
    
    logger.info("Miniature mise à jour", extra={"video_id": video_id})
