"""
Upload + programmation des Shorts sur YouTube via l'API Data v3.
Utilise privacyStatus="private" + publishAt pour la publication différée.
"""
from pathlib import Path
from datetime import datetime

from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from core.youtube_auth import get_youtube_service


def upload_scheduled_short(
    video_path: Path,
    title: str,
    description: str,
    publish_at: datetime,
    tags: list[str] | None = None,
    category_id: str = "22",  # "People & Blogs" par défaut, ajustable
) -> str:
    """
    Upload `video_path` sur YouTube, programmé pour devenir public à `publish_at`.
    Retourne le youtube_video_id.

    Note : publish_at doit être en UTC et au format RFC3339
    (ex: "2026-07-31T12:00:00Z"), sinon l'API rejette la requête.
    """
    youtube = get_youtube_service()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/*")

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        # status.progress() donne un float 0-1 si on veut logger l'avancement

    return response["id"]


def check_publish_status(youtube_video_id: str) -> str:
    """
    Interroge l'API pour connaître le privacyStatus actuel de la vidéo.
    Retourne "private" | "public" | "unlisted", ou "not_found" si la vidéo
    n'existe plus (supprimée/refusée).
    """
    youtube = get_youtube_service()

    try:
        response = youtube.videos().list(
            part="status",
            id=youtube_video_id,
        ).execute()
    except HttpError as e:
        raise RuntimeError(f"Erreur API YouTube lors du check status: {e}") from e

    items = response.get("items", [])
    if not items:
        return "not_found"

    return items[0]["status"]["privacyStatus"]
