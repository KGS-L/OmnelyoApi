"""Transitions atomiques et leases des jobs exécutés par les workers."""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from api.models import Job, JobStatus, JobType


def claim_next_job(
    db: Session, worker_id: str, accepted_types: frozenset[JobType] | None = None
) -> Job | None:
    """Réserve un job disponible sans bloquer les autres workers."""
    if accepted_types is not None and not accepted_types:
        return None
    now = datetime.now(timezone.utc)
    query = select(Job).where(
            Job.status == JobStatus.QUEUED,
            Job.available_at <= now,
            Job.attempts < Job.max_attempts,
        )
    if accepted_types is not None:
        query = query.where(Job.type.in_(accepted_types))
    job = db.scalar(
        query.order_by(Job.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        db.rollback()
        return None
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.worker_id = worker_id
    job.started_at = now
    job.heartbeat_at = now
    job.finished_at = None
    job.error_message = None
    db.commit()
    db.refresh(job)
    return job


def heartbeat_job(db: Session, job_id: uuid.UUID, worker_id: str) -> bool:
    job = db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.status == JobStatus.RUNNING,
            Job.worker_id == worker_id,
        )
    )
    if job is None:
        db.rollback()
        return False
    job.heartbeat_at = datetime.now(timezone.utc)
    db.commit()
    return True


def complete_job(
    db: Session, job_id: uuid.UUID, worker_id: str, result: dict | None = None
) -> bool:
    job = _owned_running_job(db, job_id, worker_id)
    if job is None:
        db.rollback()
        return False
    job.status = JobStatus.SUCCEEDED
    job.progress = 100
    job.result = result
    job.finished_at = datetime.now(timezone.utc)
    job.heartbeat_at = job.finished_at
    job.worker_id = None
    db.commit()
    return True


def fail_job(
    db: Session,
    job_id: uuid.UUID,
    worker_id: str,
    error_message: str,
    retry_delay_seconds: int = 30,
) -> JobStatus | None:
    job = _owned_running_job(db, job_id, worker_id)
    if job is None:
        db.rollback()
        return None
    now = datetime.now(timezone.utc)
    job.error_message = error_message[:2000]
    job.worker_id = None
    job.heartbeat_at = now
    if job.attempts < job.max_attempts:
        job.status = JobStatus.QUEUED
        job.available_at = now + timedelta(seconds=max(0, retry_delay_seconds))
        job.started_at = None
    else:
        job.status = JobStatus.FAILED
        job.finished_at = now
    db.commit()
    return job.status


def recover_stale_jobs(db: Session, stale_after_seconds: int = 300) -> int:
    """Replace en attente les jobs dont le worker ne renouvelle plus la lease."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)
    jobs = list(
        db.scalars(
            select(Job)
            .where(
                Job.status == JobStatus.RUNNING,
                or_(
                    Job.heartbeat_at < cutoff,
                    (Job.heartbeat_at.is_(None)) & (Job.started_at < cutoff),
                ),
            )
            .with_for_update(skip_locked=True)
        )
    )
    now = datetime.now(timezone.utc)
    for job in jobs:
        job.worker_id = None
        job.error_message = "Worker interrompu ou lease expirée."
        job.heartbeat_at = now
        if job.attempts < job.max_attempts:
            job.status = JobStatus.QUEUED
            job.available_at = now
            job.started_at = None
        else:
            job.status = JobStatus.FAILED
            job.finished_at = now
    db.commit()
    return len(jobs)


def _owned_running_job(
    db: Session, job_id: uuid.UUID, worker_id: str
) -> Job | None:
    return db.scalar(
        select(Job).where(
            Job.id == job_id,
            Job.status == JobStatus.RUNNING,
            Job.worker_id == worker_id,
        )
    )
