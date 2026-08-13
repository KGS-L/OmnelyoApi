"""Téléchargement et archivage d'une vidéo source distante."""
import ipaddress
import mimetypes
import shutil
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

from api.database import SessionLocal
from api.models import Job, JobType, Video, VideoStatus
from workers.registry import registry


def validate_public_source_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("L'URL source doit utiliser HTTP ou HTTPS.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("Le port de l'URL source est invalide.") from exc
    try:
        addresses = {
            result[4][0]
            for result in socket.getaddrinfo(parsed.hostname, port)
        }
    except socket.gaierror as exc:
        raise ValueError("Le domaine de la vidéo source est introuvable.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("L'URL source pointe vers un réseau non public.")


def ingest_video(job: Job, heartbeat) -> dict:
    """Télécharge une source, l'archive et rend la vidéo disponible au pipeline."""
    from core.downloader import download_video
    from core.storage_r2 import upload_to_r2
    import config

    video_id = _resolve_video(job)
    with SessionLocal() as db:
        video = db.get(Video, video_id)
        if video is None:
            raise ValueError("La vidéo associée au job est introuvable.")
        source_url = video.source_url
        if not source_url:
            raise ValueError("La vidéo ne possède aucune URL source.")
        video.status = VideoStatus.PROCESSING
        video.error_message = None
        db.commit()

    validate_public_source_url(source_url)
    work_dir = (
        config.TMP_DIR
        / "workspaces"
        / str(job.workspace_id)
        / "jobs"
        / str(job.id)
    )
    try:
        if not heartbeat():
            raise RuntimeError("Lease du job perdue avant le téléchargement.")
        downloaded_path = download_video(source_url, work_dir)
        if not heartbeat():
            raise RuntimeError("Lease du job perdue après le téléchargement.")
        storage_key = (
            f"workspaces/{job.workspace_id}/jobs/{job.id}/source/"
            f"{downloaded_path.name}"
        )
        upload_to_r2(downloaded_path, storage_key)
        mime_type, _ = mimetypes.guess_type(downloaded_path.name)
        with SessionLocal() as db:
            video = db.get(Video, video_id)
            video.storage_key = storage_key
            video.mime_type = mime_type or "video/mp4"
            video.status = VideoStatus.READY
            video.error_message = None
            db.commit()
        return {"video_id": str(video_id), "storage_key": storage_key}
    except Exception as exc:
        with SessionLocal() as db:
            video = db.get(Video, video_id)
            if video is not None:
                video.status = VideoStatus.FAILED
                video.error_message = str(exc)[:2000]
                db.commit()
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _resolve_video(job: Job) -> uuid.UUID:
    if job.video_id is not None:
        return job.video_id
    payload = job.payload or {}
    source_url = payload.get("source_url")
    if not isinstance(source_url, str) or not source_url:
        raise ValueError("Le job ingest requiert payload.source_url ou video_id.")
    title = payload.get("title")
    with SessionLocal() as db:
        video = Video(
            workspace_id=job.workspace_id,
            title=title if isinstance(title, str) else None,
            source_url=source_url,
            status=VideoStatus.PROCESSING,
        )
        db.add(video)
        db.flush()
        persisted_job = db.get(Job, job.id)
        persisted_job.video_id = video.id
        db.commit()
        return video.id


registry.register(JobType.INGEST, ingest_video)
