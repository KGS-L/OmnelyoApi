"""telegram account connections

Revision ID: 20260813_0003
Revises: 20260813_0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260813_0003"
down_revision = "20260813_0002"
branch_labels = None
depends_on = None

telegram_connection_status = postgresql.ENUM(
    "ACTIVE", "REVOKED", name="telegram_connection_status", create_type=False
)


def upgrade():
    telegram_connection_status.create(op.get_bind())
    op.create_table(
        "telegram_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", telegram_connection_status, nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_telegram_connections_workspace_user"),
    )
    op.create_index("ix_telegram_connections_workspace_id", "telegram_connections", ["workspace_id"])
    op.create_index("ix_telegram_connections_user_id", "telegram_connections", ["user_id"])
    op.create_index("ix_telegram_connections_telegram_user_id", "telegram_connections", ["telegram_user_id"], unique=True)


def downgrade():
    op.drop_table("telegram_connections")
    telegram_connection_status.drop(op.get_bind())
