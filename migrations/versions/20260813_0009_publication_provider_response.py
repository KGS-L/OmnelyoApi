"""publication provider response

Revision ID: 20260813_0009
Revises: 20260813_0008
"""
from alembic import op
import sqlalchemy as sa

revision = "20260813_0009"
down_revision = "20260813_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("publications", sa.Column("provider_response", sa.JSON()))


def downgrade():
    op.drop_column("publications", "provider_response")
