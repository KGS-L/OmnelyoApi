from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.credit_service import CreditService
from api.models import Job, JobStatus, SocialConnection, SocialConnectionStatus


class QuotaExceeded(ValueError):
    pass


class QuotaService:
    def plan_for_workspace(self, db: Session, workspace_id: uuid.UUID):
        entitlement, plan, _, _ = CreditService().workspace_summary(db, workspace_id)
        return plan

    def ensure_social_connection_available(self, db: Session, workspace_id: uuid.UUID) -> None:
        plan = self.plan_for_workspace(db, workspace_id)
        current = int(db.scalar(select(func.count()).select_from(SocialConnection).where(
            SocialConnection.workspace_id == workspace_id,
            SocialConnection.status != SocialConnectionStatus.REVOKED,
        )) or 0)
        if current >= plan.social_connections_limit:
            raise QuotaExceeded(
                f"Limite de connexions sociales atteinte pour le plan {plan.name} ({plan.social_connections_limit})."
            )

    def ensure_job_slot_available(self, db: Session, workspace_id: uuid.UUID) -> None:
        plan = self.plan_for_workspace(db, workspace_id)
        current = int(db.scalar(select(func.count()).select_from(Job).where(
            Job.workspace_id == workspace_id,
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )) or 0)
        if current >= plan.concurrent_jobs_limit:
            raise QuotaExceeded(
                f"Limite de jobs simultanés atteinte pour le plan {plan.name} ({plan.concurrent_jobs_limit})."
            )
