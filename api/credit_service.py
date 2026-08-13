from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from api.models import (
    BillingPlan,
    CreditAccount,
    CreditEntryType,
    CreditLedgerEntry,
    CreditReservation,
    CreditReservationStatus,
    WorkspaceEntitlement,
)


class InsufficientCredits(ValueError):
    pass


class CreditService:
    """Atomic credit accounting. Ledger rows are append-only."""

    def ensure_workspace(self, db: Session, workspace_id: uuid.UUID) -> tuple[WorkspaceEntitlement, CreditAccount]:
        now = datetime.now(timezone.utc)
        db.execute(
            insert(WorkspaceEntitlement)
            .values(workspace_id=workspace_id, plan_code="FREE", period_start=now, period_end=now + timedelta(days=30))
            .on_conflict_do_nothing(index_elements=[WorkspaceEntitlement.workspace_id])
        )
        db.execute(
            insert(CreditAccount)
            .values(id=uuid.uuid4(), workspace_id=workspace_id)
            .on_conflict_do_nothing(index_elements=[CreditAccount.workspace_id])
        )
        entitlement = db.get(WorkspaceEntitlement, workspace_id)
        account = db.scalar(select(CreditAccount).where(CreditAccount.workspace_id == workspace_id))
        if entitlement is None or account is None:
            raise RuntimeError("Impossible d'initialiser le compte de crédits.")
        plan = db.get(BillingPlan, entitlement.plan_code)
        if plan is None:
            raise RuntimeError("Plan de facturation introuvable.")
        self.grant(
            db,
            account,
            plan.monthly_credits,
            f"monthly:{entitlement.period_start.isoformat()}",
            "Crédits mensuels du plan",
            entitlement.period_end + timedelta(days=30),
        )
        return entitlement, account

    @staticmethod
    def balance(db: Session, account_id: uuid.UUID) -> int:
        return int(db.scalar(
            select(func.coalesce(func.sum(CreditLedgerEntry.amount), 0)).where(
                CreditLedgerEntry.account_id == account_id
            )
        ) or 0)

    def grant(
        self,
        db: Session,
        account: CreditAccount,
        amount: int,
        idempotency_key: str,
        description: str,
        expires_at: datetime | None = None,
    ) -> CreditLedgerEntry:
        if amount < 0:
            raise ValueError("Un octroi de crédits ne peut pas être négatif.")
        existing = db.scalar(select(CreditLedgerEntry).where(
            CreditLedgerEntry.account_id == account.id,
            CreditLedgerEntry.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            return existing
        entry = CreditLedgerEntry(
            account_id=account.id,
            entry_type=CreditEntryType.GRANT,
            amount=amount,
            idempotency_key=idempotency_key,
            description=description,
            expires_at=expires_at,
        )
        db.add(entry)
        db.flush()
        return entry

    def reserve(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        amount: int,
        idempotency_key: str,
        job_id: uuid.UUID | None = None,
    ) -> CreditReservation:
        if amount <= 0:
            raise ValueError("La réservation doit être positive.")
        _, account = self.ensure_workspace(db, workspace_id)
        account = db.scalar(select(CreditAccount).where(CreditAccount.id == account.id).with_for_update())
        existing = db.scalar(select(CreditReservation).where(
            CreditReservation.account_id == account.id,
            CreditReservation.idempotency_key == idempotency_key,
        ))
        if existing is not None:
            return existing
        if self.balance(db, account.id) < amount:
            raise InsufficientCredits("Solde de crédits insuffisant.")
        reservation = CreditReservation(
            account_id=account.id,
            job_id=job_id,
            amount=amount,
            status=CreditReservationStatus.ACTIVE,
            idempotency_key=idempotency_key,
        )
        db.add(reservation)
        db.flush()
        db.add(CreditLedgerEntry(
            account_id=account.id,
            reservation_id=reservation.id,
            entry_type=CreditEntryType.RESERVE,
            amount=-amount,
            idempotency_key=f"reserve:{reservation.id}",
            description="Réservation avant rendu",
        ))
        db.flush()
        return reservation

    def capture(self, db: Session, reservation_id: uuid.UUID) -> CreditReservation:
        reservation = db.scalar(
            select(CreditReservation).where(CreditReservation.id == reservation_id).with_for_update()
        )
        if reservation is None:
            raise ValueError("Réservation introuvable.")
        if reservation.status == CreditReservationStatus.CAPTURED:
            return reservation
        if reservation.status != CreditReservationStatus.ACTIVE:
            raise ValueError("Cette réservation n'est plus active.")
        reservation.status = CreditReservationStatus.CAPTURED
        reservation.resolved_at = datetime.now(timezone.utc)
        db.add(CreditLedgerEntry(
            account_id=reservation.account_id,
            reservation_id=reservation.id,
            entry_type=CreditEntryType.CAPTURE,
            amount=0,
            idempotency_key=f"capture:{reservation.id}",
            description="Rendu terminé avec succès",
        ))
        db.flush()
        return reservation

    def release(self, db: Session, reservation_id: uuid.UUID) -> CreditReservation:
        reservation = db.scalar(
            select(CreditReservation).where(CreditReservation.id == reservation_id).with_for_update()
        )
        if reservation is None:
            raise ValueError("Réservation introuvable.")
        if reservation.status == CreditReservationStatus.RELEASED:
            return reservation
        if reservation.status != CreditReservationStatus.ACTIVE:
            raise ValueError("Cette réservation n'est plus active.")
        reservation.status = CreditReservationStatus.RELEASED
        reservation.resolved_at = datetime.now(timezone.utc)
        db.add(CreditLedgerEntry(
            account_id=reservation.account_id,
            reservation_id=reservation.id,
            entry_type=CreditEntryType.RELEASE,
            amount=reservation.amount,
            idempotency_key=f"release:{reservation.id}",
            description="Crédits libérés après échec ou annulation",
        ))
        db.flush()
        return reservation

    def workspace_summary(self, db: Session, workspace_id: uuid.UUID):
        entitlement, account = self.ensure_workspace(db, workspace_id)
        plan = db.get(BillingPlan, entitlement.plan_code)
        return entitlement, plan, account, self.balance(db, account.id)
