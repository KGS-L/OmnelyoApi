"""add distinct platform roles

Revision ID: 20260813_0017
Revises: 20260813_0016
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260813_0017"
down_revision = "20260813_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    role = postgresql.ENUM("user", "admin", name="platform_role", create_type=False)
    role.create(op.get_bind(), checkfirst=True)
    op.add_column("users", sa.Column("platform_role", role, server_default="user", nullable=False))
    op.create_index("ix_users_platform_role", "users", ["platform_role"])


def downgrade() -> None:
    op.drop_index("ix_users_platform_role", table_name="users")
    op.drop_column("users", "platform_role")
    postgresql.ENUM(name="platform_role").drop(op.get_bind(), checkfirst=True)
