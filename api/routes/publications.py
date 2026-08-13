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
from api.integrations.media_validation import validate_publication_preflight
from api.integrations.social import SocialPublisherError
from api.models import (
    Channel,
    ChannelStatus,
    Job,
    JobStatus,
    JobType,
    Publication,
    PublicationStatus,
    SocialConnection,
    SocialConnectionStatus,
    Video,
    WorkspaceMembership,
)
from api.schemas import (
    JobResponse,
    PublicationBatchCreate,
    PublicationBatchPublish,
    PublicationCreate,
    PublicationResponse,
    PublicationUpdate,
)
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
    channel_state = db.execute(
        select(Channel.status, SocialConnection.status)
        .outerjoin(SocialConnection, SocialConnection.id == Channel.connection_id)
        .where(
            Channel.id == channel_id,
            Channel.workspace_id == workspace_id,
        )
    ).one_or_none()
    if channel_state is None:
        raise HTTPException(status_code=404, detail="Chaîne introuvable.")
    if (
        channel_state[0] is not ChannelStatus.ACTIVE
        or channel_state[1] is not SocialConnectionStatus.ACTIVE
    ):
        raise HTTPException(status_code=409, detail="Cette destination n'est pas connectée.")


def create_batch_publication_records(
    db: Session,
    workspace_id: uuid.UUID,
    payload: PublicationBatchCreate,
) -> list[Publication]:
    video_exists = db.scalar(
        select(Video.id).where(
            Video.id == payload.video_id,
            Video.workspace_id == workspace_id,
        )
    )
    if video_exists is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable.")
    channel_ids = [destination.channel_id for destination in payload.destinations]
    rows = db.execute(
        select(Channel.id, Channel.status, SocialConnection.status)
        .outerjoin(SocialConnection, SocialConnection.id == Channel.connection_id)
        .where(
            Channel.workspace_id == workspace_id,
            Channel.id.in_(channel_ids),
        )
    ).all()
    states = {row[0]: (row[1], row[2]) for row in rows}
    if set(states) != set(channel_ids):
        raise HTTPException(status_code=404, detail="Une destination est introuvable.")
    if any(
        channel_status is not ChannelStatus.ACTIVE
        or connection_status is not SocialConnectionStatus.ACTIVE
        for channel_status, connection_status in states.values()
    ):
        raise HTTPException(status_code=409, detail="Une destination n'est pas connectée.")
    publications: list[Publication] = []
    for destination in payload.destinations:
        _validate_future_schedule(destination.scheduled_at)
        publication = Publication(
            workspace_id=workspace_id,
            video_id=payload.video_id,
            channel_id=destination.channel_id,
            title=destination.title.strip(),
            description=destination.description,
            visibility=destination.visibility,
            scheduled_at=destination.scheduled_at,
            status=(
                PublicationStatus.SCHEDULED
                if destination.scheduled_at is not None
                else PublicationStatus.DRAFT
            ),
        )
        db.add(publication)
        publications.append(publication)
    db.commit()
    for publication in publications:
        db.refresh(publication)
    return publications


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
    return enqueue_batch_publication_records(
        db, workspace_id, [publication.id]
    )[0]


def _validate_enqueue_target(
    db: Session, workspace_id: uuid.UUID, publication: Publication
) -> None:
    video = db.scalar(
        select(Video).where(
            Video.id == publication.video_id,
            Video.workspace_id == workspace_id,
        )
    )
    if video is None or not video.rendered_storage_key:
        raise HTTPException(status_code=409, detail="La vidéo doit d'abord être rendue.")
    destination = db.execute(
        select(Channel.id, SocialConnection.id, Channel.platform)
        .join(SocialConnection, SocialConnection.id == Channel.connection_id)
        .where(
            Channel.id == publication.channel_id,
            Channel.workspace_id == workspace_id,
            Channel.status == ChannelStatus.ACTIVE,
            SocialConnection.workspace_id == workspace_id,
            SocialConnection.platform == Channel.platform,
            SocialConnection.status == SocialConnectionStatus.ACTIVE,
        )
    ).one_or_none()
    if destination is None:
        raise HTTPException(status_code=409, detail="La destination sociale n'est pas connectée.")
    try:
        validate_publication_preflight(
            platform=destination[2],
            storage_key=video.rendered_storage_key,
            duration_seconds=video.duration_seconds,
            title=publication.title,
            description=publication.description,
            visibility=publication.visibility,
            scheduled_at=publication.scheduled_at,
        )
    except SocialPublisherError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def enqueue_batch_publication_records(
    db: Session,
    workspace_id: uuid.UUID,
    publication_ids: list[uuid.UUID],
) -> list[Job]:
    locked = list(
        db.scalars(
            select(Publication)
            .where(
                Publication.workspace_id == workspace_id,
                Publication.id.in_(publication_ids),
            )
            .order_by(Publication.id)
            .with_for_update()
        )
    )
    by_id = {publication.id: publication for publication in locked}
    if set(by_id) != set(publication_ids):
        raise HTTPException(status_code=404, detail="Une publication est introuvable.")
    jobs_by_publication: dict[uuid.UUID, Job] = {}
    to_create: list[Publication] = []
    for publication_id in publication_ids:
        publication = by_id[publication_id]
        existing = db.get(Job, publication.job_id) if publication.job_id else None
        if existing is not None and existing.status in {
            JobStatus.QUEUED,
            JobStatus.RUNNING,
            JobStatus.SUCCEEDED,
        }:
            jobs_by_publication[publication_id] = existing
            continue
        allowed = EDITABLE_STATUSES | {PublicationStatus.FAILED}
        if existing is not None and existing.status is JobStatus.CANCELLED:
            allowed = allowed | {PublicationStatus.PUBLISHING}
        if publication.status not in allowed:
            raise HTTPException(
                status_code=409,
                detail="Une publication ne peut pas être mise en file.",
            )
        _validate_enqueue_target(db, workspace_id, publication)
        to_create.append(publication)
    for publication in to_create:
        job = Job(
            workspace_id=workspace_id,
            video_id=publication.video_id,
            type=JobType.PUBLISH,
            max_attempts=10,
            payload={"publication_id": str(publication.id)},
        )
        db.add(job)
        db.flush()
        publication.job_id = job.id
        publication.status = PublicationStatus.PUBLISHING
        publication.error_message = None
        jobs_by_publication[publication.id] = job
    db.commit()
    jobs = [jobs_by_publication[publication_id] for publication_id in publication_ids]
    for job in jobs:
        db.refresh(job)
    return jobs


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


@router.post(
    "/batch",
    response_model=list[PublicationResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_batch_publications(
    workspace_id: uuid.UUID,
    payload: PublicationBatchCreate,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> list[Publication]:
    return create_batch_publication_records(db, workspace_id, payload)


@router.post("/batch/publish", response_model=list[JobResponse])
def enqueue_batch_publications(
    workspace_id: uuid.UUID,
    payload: PublicationBatchPublish,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[APISettings, Depends(get_settings)],
) -> list[Job]:
    jobs = enqueue_batch_publication_records(
        db, workspace_id, payload.publication_ids
    )
    redis = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )
    for job in jobs:
        notify_workers(redis, str(job.id))
    return jobs


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
