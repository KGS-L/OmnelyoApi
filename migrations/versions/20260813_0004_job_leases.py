"""worker leases and retry scheduling

Revision ID: 20260813_0004
Revises: 20260813_0003
"""
from alembic import op
import sqlalchemy as sa

revision = "20260813_0004"
down_revision = "20260813_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "jobs",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column("jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
    op.add_column("jobs", sa.Column("worker_id", sa.String(255)))
    op.create_index("ix_jobs_available_at", "jobs", ["available_at"])
    op.create_index("ix_jobs_heartbeat_at", "jobs", ["heartbeat_at"])


def downgrade():
    op.drop_index("ix_jobs_heartbeat_at", table_name="jobs")
    op.drop_index("ix_jobs_available_at", table_name="jobs")
    op.drop_column("jobs", "worker_id")
    op.drop_column("jobs", "heartbeat_at")
    op.drop_column("jobs", "available_at")
