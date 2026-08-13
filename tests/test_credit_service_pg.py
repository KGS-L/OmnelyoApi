from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select

from api.credit_service import CreditService, InsufficientCredits
from api.database import SessionLocal
from api.models import (
    BillingPlan,
    CreditEntryType,
    CreditLedgerEntry,
    CreditReservation,
    CreditReservationStatus,
    Job,
    JobStatus,
    JobType,
    Workspace,
)


@pytest.fixture()
def credit_db():
    session = SessionLocal()
    # No skip: a migrated PostgreSQL is mandatory for these tests.
    assert session.scalar(select(BillingPlan.code).where(BillingPlan.code == "FREE")) == "FREE"
    workspace = Workspace(name="Credit Test", slug=f"credit-{uuid.uuid4().hex[:10]}")
    session.add(workspace)
    session.commit()
    yield session, workspace
    session.rollback()
    session.execute(delete(Workspace).where(Workspace.id == workspace.id))
    session.commit()
    session.close()


def test_free_plan_is_lazily_provisioned_once(credit_db):
    session, workspace = credit_db
    service = CreditService()
    entitlement, plan, account, balance = service.workspace_summary(session, workspace.id)
    session.commit()
    assert entitlement.plan_code == "FREE"
    assert plan.monthly_credits == 3
    assert plan.social_connections_limit == 1
    assert balance == 3

    _, _, same_account, same_balance = service.workspace_summary(session, workspace.id)
    session.commit()
    assert same_account.id == account.id
    assert same_balance == 3
    grants = session.scalars(select(CreditLedgerEntry).where(
        CreditLedgerEntry.account_id == account.id,
        CreditLedgerEntry.entry_type == CreditEntryType.GRANT,
    )).all()
    assert len(grants) == 1


def test_reserve_capture_is_idempotent(credit_db):
    session, workspace = credit_db
    service = CreditService()
    reservation = service.reserve(session, workspace.id, 1, "render:one")
    duplicate = service.reserve(session, workspace.id, 1, "render:one")
    assert duplicate.id == reservation.id
    assert service.workspace_summary(session, workspace.id)[3] == 2
    service.capture(session, reservation.id)
    service.capture(session, reservation.id)
    session.commit()
    assert reservation.status == CreditReservationStatus.CAPTURED
    assert service.workspace_summary(session, workspace.id)[3] == 2


def test_release_returns_reserved_credit_once(credit_db):
    session, workspace = credit_db
    service = CreditService()
    reservation = service.reserve(session, workspace.id, 2, "render:failed")
    assert service.workspace_summary(session, workspace.id)[3] == 1
    service.release(session, reservation.id)
    service.release(session, reservation.id)
    session.commit()
    assert reservation.status == CreditReservationStatus.RELEASED
    assert service.workspace_summary(session, workspace.id)[3] == 3


def test_cannot_reserve_more_than_balance(credit_db):
    session, workspace = credit_db
    with pytest.raises(InsufficientCredits):
        CreditService().reserve(session, workspace.id, 4, "render:too-expensive")
    session.rollback()


def test_render_completion_captures_reservation(credit_db):
    from workers.job_state import complete_job

    session, workspace = credit_db
    job = Job(
        workspace_id=workspace.id,
        type=JobType.RENDER,
        status=JobStatus.RUNNING,
        worker_id="worker-test",
    )
    session.add(job)
    session.flush()
    reservation = CreditService().reserve(session, workspace.id, 1, f"render-job:{job.id}", job.id)
    session.commit()
    assert complete_job(session, job.id, "worker-test", {"ok": True}) is True
    session.refresh(reservation)
    assert reservation.status == CreditReservationStatus.CAPTURED


def test_final_render_failure_releases_reservation(credit_db):
    from workers.job_state import fail_job

    session, workspace = credit_db
    job = Job(
        workspace_id=workspace.id,
        type=JobType.RENDER,
        status=JobStatus.RUNNING,
        worker_id="worker-test",
        attempts=1,
        max_attempts=1,
    )
    session.add(job)
    session.flush()
    reservation = CreditService().reserve(session, workspace.id, 1, f"render-job:{job.id}", job.id)
    session.commit()
    assert fail_job(session, job.id, "worker-test", "boom") == JobStatus.FAILED
    session.refresh(reservation)
    assert reservation.status == CreditReservationStatus.RELEASED
    assert CreditService().workspace_summary(session, workspace.id)[3] == 3
