"""Création et suivi des traitements vidéo persistants."""
import uuid
import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from redis import Redis

from api.database import get_db
from api.dependencies import get_current_workspace_membership
from api.models import Job, JobStatus, JobType, Video, WorkspaceMembership
from api.schemas import JobCreate, JobResponse
from api.config import APISettings, get_settings
from workers.signals import notify_workers

router = APIRouter(prefix="/workspaces/{workspace_id}/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)


def _get_job(db: Session, workspace_id: uuid.UUID, job_id: uuid.UUID) -> Job:
    job = db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.workspace_id == workspace_id,
        )
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable.")
    return job


def _ensure_video_in_workspace(
    db: Session, workspace_id: uuid.UUID, video_id: uuid.UUID
) -> None:
    exists_in_workspace = db.scalar(
        select(Video.id).where(
            Video.id == video_id,
            Video.workspace_id == workspace_id,
        )
    )
    if exists_in_workspace is None:
        raise HTTPException(status_code=404, detail="Vidéo introuvable.")


def cancel_job_record(job: Job) -> None:
    if job.status is not JobStatus.QUEUED:
        raise HTTPException(
            status_code=409,
            detail="Seul un job en attente peut être annulé.",
        )
    job.status = JobStatus.CANCELLED
    job.finished_at = datetime.now(timezone.utc)
    job.worker_id = None


def retry_job_record(job: Job) -> None:
    if job.status is not JobStatus.FAILED:
        raise HTTPException(
            status_code=409,
            detail="Seul un job échoué peut être relancé.",
        )
    if job.attempts >= job.max_attempts:
        raise HTTPException(
            status_code=409,
            detail="Le nombre maximal de tentatives est atteint.",
        )
    job.status = JobStatus.QUEUED
    job.progress = 0
    job.available_at = datetime.now(timezone.utc)
    job.error_message = None
    job.started_at = None
    job.heartbeat_at = None
    job.worker_id = None
    job.finished_at = None
    job.result = None


@router.get("", response_model=list[JobResponse])
def list_jobs(
    workspace_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
    job_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    job_type: Annotated[JobType | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Job]:
    query = select(Job).where(Job.workspace_id == workspace_id)
    if job_status is not None:
        query = query.where(Job.status == job_status)
    if job_type is not None:
        query = query.where(Job.type == job_type)
    return list(db.scalars(query.order_by(Job.created_at.desc()).limit(limit).offset(offset)))


@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[APISettings, Depends(get_settings)],
) -> Job:
    return _get_job(db, workspace_id, job_id)


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    workspace_id: uuid.UUID,
    payload: JobCreate,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Job:
    if payload.video_id is not None:
        _ensure_video_in_workspace(db, workspace_id, payload.video_id)
    job = Job(workspace_id=workspace_id, **payload.model_dump())
    db.add(job)
    db.commit()
    db.refresh(job)
    notify_workers(
        Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        ),
        str(job.id),
    )
    return job


@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Job:
    job = _get_job(db, workspace_id, job_id)
    cancel_job_record(job)
    db.commit()
    db.refresh(job)
    return job


@router.post("/{job_id}/retry", response_model=JobResponse)
def retry_job(
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Job:
    job = _get_job(db, workspace_id, job_id)
    retry_job_record(job)
    db.commit()
    db.refresh(job)
    return job
