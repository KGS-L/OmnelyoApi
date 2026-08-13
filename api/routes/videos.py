"""Gestion des vidéos d'un workspace."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.config import APISettings, get_settings
from api.dependencies import get_current_workspace_membership, require_workspace_roles
from api.models import Job, Publication, Video, VideoStatus, WorkspaceMembership, WorkspaceRole
from api.schemas import VideoCreate, VideoDownloadURLResponse, VideoResponse, VideoUpdate

router = APIRouter(prefix="/workspaces/{workspace_id}/videos", tags=["videos"])


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
    expected_prefix = f"workspaces/{workspace_id}/"
    if not storage_key.startswith(expected_prefix):
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
