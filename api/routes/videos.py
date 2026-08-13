"""Gestion des vidéos d'un workspace."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies import get_current_workspace_membership, require_workspace_roles
from api.models import Job, Publication, Video, VideoStatus, WorkspaceMembership, WorkspaceRole
from api.schemas import VideoCreate, VideoResponse, VideoUpdate

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
