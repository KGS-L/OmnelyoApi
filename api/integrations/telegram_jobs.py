"""Accès du bot Telegram au pipeline PostgreSQL multi-tenant."""
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.integrations.telegram import get_active_telegram_connection
from api.models import Job, JobStatus, JobType, Video, VideoStatus
from core.storage_keys import upload_source_key


def enqueue_url_from_telegram(
    db: Session, telegram_user_id: int, source_url: str, title: str | None = None
) -> Job:
    connection = _connection(db, telegram_user_id)
    video = Video(
        workspace_id=connection.workspace_id,
        source_url=source_url,
        title=title,
        status=VideoStatus.QUEUED,
    )
    db.add(video)
    db.flush()
    job = Job(
        workspace_id=connection.workspace_id,
        video_id=video.id,
        type=JobType.INGEST,
        payload={"source": "telegram", "telegram_user_id": telegram_user_id},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def import_video_from_telegram(
    db: Session,
    telegram_user_id: int,
    local_path: Path,
    mime_type: str,
    duration_seconds: float,
    title: str,
) -> Video:
    from core.storage_r2 import delete_from_r2, upload_to_r2

    connection = _connection(db, telegram_user_id)
    video_id = uuid.uuid4()
    suffix_by_mime = {
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "video/webm": ".webm",
    }
    try:
        suffix = suffix_by_mime[mime_type]
    except KeyError as exc:
        raise ValueError("Type de vidéo Telegram non pris en charge.") from exc
    storage_key = upload_source_key(connection.workspace_id, video_id, suffix)
    upload_to_r2(local_path, storage_key)
    try:
        video = Video(
            id=video_id,
            workspace_id=connection.workspace_id,
            title=title,
            storage_key=storage_key,
            rendered_storage_key=storage_key,
            mime_type=mime_type,
            duration_seconds=duration_seconds,
            status=VideoStatus.READY,
        )
        db.add(video)
        db.commit()
        db.refresh(video)
        return video
    except Exception:
        db.rollback()
        delete_from_r2(storage_key)
        raise


def list_jobs_for_telegram(
    db: Session, telegram_user_id: int, limit: int = 10
) -> list[Job]:
    connection = _connection(db, telegram_user_id)
    return list(
        db.scalars(
            select(Job)
            .where(Job.workspace_id == connection.workspace_id)
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
    )


def cancel_job_from_telegram(
    db: Session, telegram_user_id: int, job_id: uuid.UUID
) -> bool:
    connection = _connection(db, telegram_user_id)
    job = db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.workspace_id == connection.workspace_id,
            Job.status == JobStatus.QUEUED,
        )
    )
    if job is None:
        return False
    job.status = JobStatus.CANCELLED
    db.commit()
    return True


def _connection(db: Session, telegram_user_id: int):
    connection = get_active_telegram_connection(db, telegram_user_id)
    if connection is None:
        raise ValueError(
            "Connecte d'abord Telegram depuis Paramètres → Intégrations du site."
        )
    return connection
