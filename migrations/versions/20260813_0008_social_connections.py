"""social connections and encrypted credentials

Revision ID: 20260813_0008
Revises: 20260813_0007
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260813_0008"
down_revision = "20260813_0007"
branch_labels = None
depends_on = None

connection_status = postgresql.ENUM(
    "ACTIVE", "EXPIRED", "REVOKED", name="social_connection_status", create_type=False
)
channel_platform = postgresql.ENUM(name="channel_platform", create_type=False)


def upgrade():
    connection_status.create(op.get_bind())
    op.create_table(
        "social_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", channel_platform, nullable=False),
        sa.Column("provider_account_id", sa.String(255), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text()),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("status", connection_status, nullable=False),
        sa.Column("provider_metadata", sa.JSON()),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id", "platform", "provider_account_id",
            name="uq_social_connections_workspace_provider_account",
        ),
    )
    for column in ("workspace_id", "platform", "expires_at", "status"):
        op.create_index(f"ix_social_connections_{column}", "social_connections", [column])
    op.add_column(
        "channels", sa.Column("connection_id", postgresql.UUID(as_uuid=True))
    )
    op.create_foreign_key(
        "fk_channels_connection_id_social_connections",
        "channels", "social_connections", ["connection_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_channels_connection_id", "channels", ["connection_id"])


def downgrade():
    op.drop_index("ix_channels_connection_id", table_name="channels")
    op.drop_constraint(
        "fk_channels_connection_id_social_connections", "channels", type_="foreignkey"
    )
    op.drop_column("channels", "connection_id")
    op.drop_table("social_connections")
    connection_status.drop(op.get_bind())
