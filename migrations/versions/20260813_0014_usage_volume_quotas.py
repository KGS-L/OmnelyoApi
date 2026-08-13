"""usage events, video sizes and retention

Revision ID: 20260813_0014
Revises: 20260813_0013
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260813_0014"
down_revision = "20260813_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    usage_metric = postgresql.ENUM(
        "source_seconds", "publications", name="usage_metric", create_type=False
    )
    usage_metric.create(op.get_bind(), checkfirst=True)
    op.add_column("videos", sa.Column("storage_size_bytes", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("videos", sa.Column("rendered_size_bytes", sa.BigInteger(), server_default="0", nullable=False))
    op.add_column("videos", sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_videos_retention_expires_at", "videos", ["retention_expires_at"])
    op.create_table(
        "usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", usage_metric, nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_usage_events_quantity_positive"),
        sa.UniqueConstraint("workspace_id", "metric", "idempotency_key", name="uq_usage_events_ws_metric_idem"),
    )
    for column in ("workspace_id", "metric", "occurred_at"):
        op.create_index(f"ix_usage_events_{column}", "usage_events", [column])


def downgrade() -> None:
    op.drop_table("usage_events")
    op.drop_index("ix_videos_retention_expires_at", table_name="videos")
    op.drop_column("videos", "retention_expires_at")
    op.drop_column("videos", "rendered_size_bytes")
    op.drop_column("videos", "storage_size_bytes")
    postgresql.ENUM(name="usage_metric").drop(op.get_bind(), checkfirst=True)
