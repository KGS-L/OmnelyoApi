"""Gestion des vidéos d'un workspace."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.config import APISettings, get_settings
from api.dependencies import get_current_workspace_membership, require_workspace_roles
from api.models import Job, Publication, Video, VideoStatus, WorkspaceMembership, WorkspaceRole
from api.media_upload import detect_video_type, stream_upload
from core.storage_keys import belongs_to_workspace, upload_source_key
from api.schemas import VideoCreate, VideoDownloadURLResponse, VideoResponse, VideoUpdate
from api.quota_service import QuotaExceeded, QuotaService

router = APIRouter(prefix="/workspaces/{workspace_id}/videos", tags=["videos"])


@router.post("/upload", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
async def upload_video(
    workspace_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[APISettings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=255)] = None,
) -> Video:
    """Reçoit une vidéo par morceaux, vérifie sa signature puis l'archive."""
    from core.storage_r2 import delete_from_r2, upload_to_r2
    import config

    video_id = uuid.uuid4()
    temporary = (
        config.TMP_DIR / "workspaces" / str(workspace_id) / "uploads" / f"{video_id}.part"
    )
    storage_key = None
    try:
        await stream_upload(file, temporary, settings.video_upload_max_bytes)
        size_bytes = temporary.stat().st_size
        from core.video_processor import probe_video_duration
        duration_seconds = probe_video_duration(temporary)
        quota = QuotaService()
        quota.ensure_storage_available(db, workspace_id, size_bytes)
        quota.record_source_seconds(db, workspace_id, max(1, int(duration_seconds + 0.999)), f"source-video:{video_id}")
        retention_expires_at = quota.retention_deadline(db, workspace_id)
        with temporary.open("rb") as uploaded_file:
            mime_type, suffix = detect_video_type(uploaded_file.read(32))
        storage_key = upload_source_key(workspace_id, video_id, suffix)
        upload_to_r2(temporary, storage_key)
        video = Video(
            id=video_id,
            workspace_id=workspace_id,
            title=title.strip() if title and title.strip() else file.filename,
            storage_key=storage_key,
            mime_type=mime_type,
            duration_seconds=duration_seconds,
            storage_size_bytes=size_bytes,
            retention_expires_at=retention_expires_at,
            status=VideoStatus.UPLOADED,
        )
        db.add(video)
        db.commit()
        db.refresh(video)
        return video
    except QuotaExceeded as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        if storage_key is not None:
            try:
                delete_from_r2(storage_key)
            except RuntimeError:
                pass
        raise
    finally:
        temporary.unlink(missing_ok=True)


def _get_video(db: Session, workspace_id: uuid.UUID, video_id: uuid.UUID) -> Video:
    video = db.scalar(
        select(Video).where(
            Video.id == video_id,
            Video.workspace_id == workspace_id,
        )
    )
    if not video:
        raise HTTPException(status_code=404, detail="Vidéo introuvable.")
    return video


@router.get("", response_model=list[VideoResponse])
def list_videos(
    workspace_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
    video_status: Annotated[VideoStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Video]:
    query = select(Video).where(Video.workspace_id == workspace_id)
    if video_status is not None:
        query = query.where(Video.status == video_status)
    return list(
        db.scalars(query.order_by(Video.created_at.desc()).limit(limit).offset(offset))
    )


@router.get("/{video_id}", response_model=VideoResponse)
def get_video(
    workspace_id: uuid.UUID,
    video_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Video:
    return _get_video(db, workspace_id, video_id)


@router.get("/{video_id}/download-url", response_model=VideoDownloadURLResponse)
def get_video_download_url(
    workspace_id: uuid.UUID,
    video_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[APISettings, Depends(get_settings)],
    artifact: Literal["source", "rendered"] = "rendered",
) -> VideoDownloadURLResponse:
    from core.storage_r2 import create_presigned_download_url

    video = _get_video(db, workspace_id, video_id)
    storage_key = video.rendered_storage_key if artifact == "rendered" else video.storage_key
    if not storage_key:
        raise HTTPException(status_code=404, detail="Cet artefact vidéo n'est pas disponible.")
    if not belongs_to_workspace(storage_key, workspace_id):
        raise HTTPException(status_code=409, detail="La clé de stockage n'est pas isolée par workspace.")
    try:
        url = create_presigned_download_url(
            storage_key, settings.r2_signed_url_ttl_seconds
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return VideoDownloadURLResponse(
        url=url,
        expires_at=datetime.now(timezone.utc)
        + timedelta(seconds=settings.r2_signed_url_ttl_seconds),
    )


@router.post("", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
def create_video(
    workspace_id: uuid.UUID,
    payload: VideoCreate,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Video:
    values = payload.model_dump()
    if values["source_url"] is not None:
        values["source_url"] = str(values["source_url"])
    video = Video(workspace_id=workspace_id, **values)
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


@router.patch("/{video_id}", response_model=VideoResponse)
def update_video(
    workspace_id: uuid.UUID,
    video_id: uuid.UUID,
    payload: VideoUpdate,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Video:
    video = _get_video(db, workspace_id, video_id)
    video.title = payload.title.strip()
    db.commit()
    db.refresh(video)
    return video


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video(
    workspace_id: uuid.UUID,
    video_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership,
        Depends(require_workspace_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    video = _get_video(db, workspace_id, video_id)
    has_jobs = db.scalar(select(exists().where(Job.video_id == video.id)))
    has_publications = db.scalar(
        select(exists().where(Publication.video_id == video.id))
    )
    is_referenced = has_jobs or has_publications
    if is_referenced:
        raise HTTPException(
            status_code=409,
            detail="Cette vidéo possède des traitements ou publications et doit être conservée.",
        )
    db.delete(video)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
