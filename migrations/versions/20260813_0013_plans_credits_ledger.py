"""plans, workspace entitlements and immutable credit ledger

Revision ID: 20260813_0013
Revises: 20260813_0012
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260813_0013"
down_revision = "20260813_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    reservation_status = postgresql.ENUM(
        "active", "captured", "released", name="credit_reservation_status", create_type=False
    )
    reservation_status.create(op.get_bind(), checkfirst=True)
    entry_type = postgresql.ENUM(
        "grant", "reserve", "capture", "release", "refund", "expire", "adjustment",
        name="credit_entry_type", create_type=False,
    )
    entry_type.create(op.get_bind(), checkfirst=True)

    plans = op.create_table(
        "billing_plans",
        sa.Column("code", sa.String(32), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("monthly_credits", sa.Integer(), nullable=False),
        sa.Column("social_connections_limit", sa.Integer(), nullable=False),
        sa.Column("workspaces_limit", sa.Integer(), nullable=False),
        sa.Column("members_per_workspace_limit", sa.Integer(), nullable=False),
        sa.Column("concurrent_jobs_limit", sa.Integer(), nullable=False),
        sa.Column("source_minutes_monthly_limit", sa.Integer(), nullable=False),
        sa.Column("publications_monthly_limit", sa.Integer(), nullable=False),
        sa.Column("storage_bytes_limit", sa.BigInteger(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_billing_plans_active", "billing_plans", ["active"])
    op.bulk_insert(plans, [
        {"code": "FREE", "name": "Gratuit", "monthly_credits": 3, "social_connections_limit": 1, "workspaces_limit": 1, "members_per_workspace_limit": 1, "concurrent_jobs_limit": 1, "source_minutes_monthly_limit": 30, "publications_monthly_limit": 10, "storage_bytes_limit": 1_073_741_824, "retention_days": 7, "active": True},
        {"code": "CREATOR", "name": "Creator", "monthly_credits": 30, "social_connections_limit": 2, "workspaces_limit": 1, "members_per_workspace_limit": 1, "concurrent_jobs_limit": 1, "source_minutes_monthly_limit": 300, "publications_monthly_limit": 120, "storage_bytes_limit": 10_737_418_240, "retention_days": 60, "active": True},
        {"code": "PRO", "name": "Pro", "monthly_credits": 100, "social_connections_limit": 8, "workspaces_limit": 3, "members_per_workspace_limit": 5, "concurrent_jobs_limit": 2, "source_minutes_monthly_limit": 1200, "publications_monthly_limit": 800, "storage_bytes_limit": 53_687_091_200, "retention_days": 180, "active": True},
    ])

    op.create_table(
        "workspace_entitlements",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("plan_code", sa.String(32), sa.ForeignKey("billing_plans.code"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_workspace_entitlements_plan_code", "workspace_entitlements", ["plan_code"])
    op.create_index("ix_workspace_entitlements_period_end", "workspace_entitlements", ["period_end"])

    op.create_table(
        "credit_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_credit_accounts_workspace_id", "credit_accounts", ["workspace_id"])

    op.create_table(
        "credit_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credit_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, unique=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", reservation_status, server_default="active", nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount > 0", name="ck_credit_reservations_amount_positive"),
        sa.UniqueConstraint("account_id", "idempotency_key", name="uq_credit_reservations_account_idem"),
    )
    op.create_index("ix_credit_reservations_account_id", "credit_reservations", ["account_id"])
    op.create_index("ix_credit_reservations_job_id", "credit_reservations", ["job_id"])
    op.create_index("ix_credit_reservations_status", "credit_reservations", ["status"])

    op.create_table(
        "credit_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credit_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credit_reservations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entry_type", entry_type, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("account_id", "idempotency_key", name="uq_credit_ledger_account_idem"),
    )
    for column in ("account_id", "reservation_id", "entry_type", "expires_at", "created_at"):
        op.create_index(f"ix_credit_ledger_entries_{column}", "credit_ledger_entries", [column])

    # Existing workspaces start on FREE. Credits are granted lazily by the
    # service so the operation remains idempotent and auditable.
    op.execute(sa.text("""
        INSERT INTO workspace_entitlements (workspace_id, plan_code, period_start, period_end)
        SELECT id, 'FREE', now(), now() + interval '30 days' FROM workspaces
        ON CONFLICT (workspace_id) DO NOTHING
    """))
    op.execute(sa.text("""
        INSERT INTO credit_accounts (id, workspace_id)
        SELECT gen_random_uuid(), id FROM workspaces
        ON CONFLICT (workspace_id) DO NOTHING
    """))


def downgrade() -> None:
    op.drop_table("credit_ledger_entries")
    op.drop_table("credit_reservations")
    op.drop_table("credit_accounts")
    op.drop_table("workspace_entitlements")
    op.drop_table("billing_plans")
    postgresql.ENUM(name="credit_entry_type").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="credit_reservation_status").drop(op.get_bind(), checkfirst=True)
