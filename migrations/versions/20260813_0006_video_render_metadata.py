"""video render metadata

Revision ID: 20260813_0006
Revises: 20260813_0005
"""
from alembic import op
import sqlalchemy as sa

revision = "20260813_0006"
down_revision = "20260813_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("videos", sa.Column("rendered_storage_key", sa.String(1024)))
    op.add_column("videos", sa.Column("narration_text", sa.Text()))
    op.add_column("videos", sa.Column("rendered_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("videos", "rendered_at")
    op.drop_column("videos", "narration_text")
    op.drop_column("videos", "rendered_storage_key")
