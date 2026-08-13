from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.credit_service import CreditService
from api.models import (
    CreditAccount, Job, JobStatus, SocialConnection, SocialConnectionStatus,
    UsageEvent, UsageMetric, Video,
)


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

    def record_source_seconds(self, db: Session, workspace_id: uuid.UUID, seconds: int, idempotency_key: str) -> UsageEvent:
        return self._record_monthly_usage(
            db, workspace_id, UsageMetric.SOURCE_SECONDS, seconds, idempotency_key,
            lambda plan: plan.source_minutes_monthly_limit * 60, "minutes de vidéo source",
        )

    def record_publications(self, db: Session, workspace_id: uuid.UUID, count: int, idempotency_key: str) -> UsageEvent:
        return self._record_monthly_usage(
            db, workspace_id, UsageMetric.PUBLICATIONS, count, idempotency_key,
            lambda plan: plan.publications_monthly_limit, "publications mensuelles",
        )

    def _record_monthly_usage(self, db, workspace_id, metric, quantity, idempotency_key, limit_getter, label):
        if quantity <= 0:
            raise ValueError("La quantité d'usage doit être positive.")
        entitlement, account = CreditService().ensure_workspace(db, workspace_id)
        existing = db.scalar(select(UsageEvent).where(
            UsageEvent.workspace_id == workspace_id,
            UsageEvent.metric == metric,
            UsageEvent.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            return existing
        db.scalar(select(CreditAccount).where(CreditAccount.id == account.id).with_for_update())
        plan = self.plan_for_workspace(db, workspace_id)
        used = int(db.scalar(select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
            UsageEvent.workspace_id == workspace_id,
            UsageEvent.metric == metric,
            UsageEvent.occurred_at >= entitlement.period_start,
            UsageEvent.occurred_at < entitlement.period_end,
        )) or 0)
        limit = int(limit_getter(plan))
        if used + quantity > limit:
            raise QuotaExceeded(f"Quota de {label} dépassé pour le plan {plan.name} ({limit}).")
        event = UsageEvent(workspace_id=workspace_id, metric=metric, quantity=quantity, idempotency_key=idempotency_key)
        db.add(event)
        db.flush()
        return event

    def ensure_storage_available(self, db: Session, workspace_id: uuid.UUID, additional_bytes: int) -> None:
        if additional_bytes < 0:
            raise ValueError("La taille supplémentaire ne peut pas être négative.")
        _, account = CreditService().ensure_workspace(db, workspace_id)
        db.scalar(select(CreditAccount).where(CreditAccount.id == account.id).with_for_update())
        plan = self.plan_for_workspace(db, workspace_id)
        used = int(db.scalar(select(func.coalesce(func.sum(
            Video.storage_size_bytes + Video.rendered_size_bytes
        ), 0)).where(Video.workspace_id == workspace_id)) or 0)
        if used + additional_bytes > plan.storage_bytes_limit:
            raise QuotaExceeded(
                f"Quota de stockage dépassé pour le plan {plan.name} ({plan.storage_bytes_limit} octets)."
            )

    def retention_deadline(self, db: Session, workspace_id: uuid.UUID) -> datetime:
        plan = self.plan_for_workspace(db, workspace_id)
        return datetime.now(timezone.utc) + timedelta(days=plan.retention_days)

    def usage_summary(self, db: Session, workspace_id: uuid.UUID) -> dict[str, int]:
        entitlement, _, _, _ = CreditService().workspace_summary(db, workspace_id)
        rows = dict(db.execute(
            select(UsageEvent.metric, func.coalesce(func.sum(UsageEvent.quantity), 0))
            .where(
                UsageEvent.workspace_id == workspace_id,
                UsageEvent.occurred_at >= entitlement.period_start,
                UsageEvent.occurred_at < entitlement.period_end,
            )
            .group_by(UsageEvent.metric)
        ).all())
        storage = int(db.scalar(select(func.coalesce(func.sum(
            Video.storage_size_bytes + Video.rendered_size_bytes
        ), 0)).where(Video.workspace_id == workspace_id)) or 0)
        return {
            "source_seconds": int(rows.get(UsageMetric.SOURCE_SECONDS, 0)),
            "publications": int(rows.get(UsageMetric.PUBLICATIONS, 0)),
            "storage_bytes": storage,
        }
