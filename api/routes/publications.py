"""Planification et suivi des publications sociales."""
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from redis import Redis

from api.config import APISettings, get_settings
from api.database import get_db
from api.dependencies import get_current_workspace_membership
from api.models import (
    Channel,
    ChannelStatus,
    Job,
    JobStatus,
    JobType,
    Publication,
    PublicationStatus,
    Video,
    WorkspaceMembership,
)
from api.schemas import JobResponse, PublicationCreate, PublicationResponse, PublicationUpdate
from workers.signals import notify_workers

router = APIRouter(
    prefix="/workspaces/{workspace_id}/publications", tags=["publications"]
)

EDITABLE_STATUSES = frozenset({PublicationStatus.DRAFT, PublicationStatus.SCHEDULED})


def _get_publication(
    db: Session, workspace_id: uuid.UUID, publication_id: uuid.UUID
) -> Publication:
    publication = db.scalar(
        select(Publication).where(
            Publication.id == publication_id,
            Publication.workspace_id == workspace_id,
        )
    )
    if not publication:
        raise HTTPException(status_code=404, detail="Publication introuvable.")
    return publication


def _ensure_targets_in_workspace(
    db: Session,
    workspace_id: uuid.UUID,
    video_id: uuid.UUID,
    channel_id: uuid.UUID,
) -> None:
    video_exists = db.scalar(
        select(Video.id).where(
            Video.id == video_id,
            Video.workspace_id == workspace_id,
        )
    )
    if video_exists is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable.")
    channel_status = db.scalar(
        select(Channel.status).where(
            Channel.id == channel_id,
            Channel.workspace_id == workspace_id,
        )
    )
    if channel_status is None:
        raise HTTPException(status_code=404, detail="Chaîne introuvable.")
    if channel_status is not ChannelStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="Cette chaîne n'est pas active.")


def _validate_future_schedule(scheduled_at: datetime | None) -> None:
    if scheduled_at is not None and scheduled_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=422,
            detail="La date de publication doit être dans le futur.",
        )


def update_publication_record(
    publication: Publication, payload: PublicationUpdate
) -> None:
    if publication.status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Cette publication ne peut plus être modifiée.",
        )
    changes = payload.model_dump(exclude_unset=True)
    if "scheduled_at" in changes:
        _validate_future_schedule(changes["scheduled_at"])
        publication.status = (
            PublicationStatus.SCHEDULED
            if changes["scheduled_at"] is not None
            else PublicationStatus.DRAFT
        )
    for field, value in changes.items():
        setattr(publication, field, value.strip() if isinstance(value, str) else value)


def cancel_publication_record(publication: Publication) -> None:
    if publication.status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail="Cette publication ne peut plus être annulée.",
        )
    publication.status = PublicationStatus.CANCELLED


def enqueue_publication_record(
    db: Session, workspace_id: uuid.UUID, publication: Publication
) -> Job:
    publication = db.scalar(
        select(Publication)
        .where(
            Publication.id == publication.id,
            Publication.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if publication is None:
        raise HTTPException(status_code=404, detail="Publication introuvable.")
    if publication.job_id is not None:
        existing = db.get(Job, publication.job_id)
        if existing is not None and existing.status in {
            JobStatus.QUEUED,
            JobStatus.RUNNING,
            JobStatus.SUCCEEDED,
        }:
            return existing
    if publication.status not in EDITABLE_STATUSES | {PublicationStatus.FAILED}:
        raise HTTPException(status_code=409, detail="Cette publication ne peut pas être mise en file.")
    video = db.scalar(
        select(Video).where(
            Video.id == publication.video_id,
            Video.workspace_id == workspace_id,
        )
    )
    if video is None or not video.rendered_storage_key:
        raise HTTPException(status_code=409, detail="La vidéo doit d'abord être rendue.")
    channel = db.scalar(
        select(Channel).where(
            Channel.id == publication.channel_id,
            Channel.workspace_id == workspace_id,
            Channel.status == ChannelStatus.ACTIVE,
        )
    )
    if channel is None or channel.connection_id is None:
        raise HTTPException(status_code=409, detail="La destination sociale n'est pas connectée.")
    job = Job(
        workspace_id=workspace_id,
        video_id=publication.video_id,
        type=JobType.PUBLISH,
        payload={"publication_id": str(publication.id)},
    )
    db.add(job)
    db.flush()
    publication.job_id = job.id
    publication.status = PublicationStatus.PUBLISHING
    publication.error_message = None
    db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=list[PublicationResponse])
def list_publications(
    workspace_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
    publication_status: Annotated[
        PublicationStatus | None, Query(alias="status")
    ] = None,
    channel_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Publication]:
    query = select(Publication).where(Publication.workspace_id == workspace_id)
    if publication_status is not None:
        query = query.where(Publication.status == publication_status)
    if channel_id is not None:
        query = query.where(Publication.channel_id == channel_id)
    return list(
        db.scalars(
            query.order_by(Publication.created_at.desc()).limit(limit).offset(offset)
        )
    )


@router.get("/{publication_id}", response_model=PublicationResponse)
def get_publication(
    workspace_id: uuid.UUID,
    publication_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Publication:
    return _get_publication(db, workspace_id, publication_id)


@router.post("", response_model=PublicationResponse, status_code=status.HTTP_201_CREATED)
def create_publication(
    workspace_id: uuid.UUID,
    payload: PublicationCreate,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Publication:
    _ensure_targets_in_workspace(
        db, workspace_id, payload.video_id, payload.channel_id
    )
    _validate_future_schedule(payload.scheduled_at)
    values = payload.model_dump()
    values["title"] = values["title"].strip()
    values["status"] = (
        PublicationStatus.SCHEDULED
        if payload.scheduled_at is not None
        else PublicationStatus.DRAFT
    )
    publication = Publication(workspace_id=workspace_id, **values)
    db.add(publication)
    db.commit()
    db.refresh(publication)
    return publication


@router.patch("/{publication_id}", response_model=PublicationResponse)
def update_publication(
    workspace_id: uuid.UUID,
    publication_id: uuid.UUID,
    payload: PublicationUpdate,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Publication:
    publication = _get_publication(db, workspace_id, publication_id)
    update_publication_record(publication, payload)
    db.commit()
    db.refresh(publication)
    return publication


@router.post("/{publication_id}/cancel", response_model=PublicationResponse)
def cancel_publication(
    workspace_id: uuid.UUID,
    publication_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Publication:
    publication = _get_publication(db, workspace_id, publication_id)
    cancel_publication_record(publication)
    db.commit()
    db.refresh(publication)
    return publication


@router.post("/{publication_id}/publish", response_model=JobResponse)
def enqueue_publication(
    workspace_id: uuid.UUID,
    publication_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[APISettings, Depends(get_settings)],
) -> Job:
    publication = _get_publication(db, workspace_id, publication_id)
    job = enqueue_publication_record(db, workspace_id, publication)
    notify_workers(
        Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        ),
        str(job.id),
    )
    return job
