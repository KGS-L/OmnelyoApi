"""add social channel platforms

Revision ID: 20260813_0007
Revises: 20260813_0006
"""
from alembic import op

revision = "20260813_0007"
down_revision = "20260813_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE channel_platform ADD VALUE IF NOT EXISTS 'TIKTOK'")
    op.execute("ALTER TYPE channel_platform ADD VALUE IF NOT EXISTS 'FACEBOOK'")
    op.execute("ALTER TYPE channel_platform ADD VALUE IF NOT EXISTS 'INSTAGRAM'")


def downgrade():
    # PostgreSQL ne sait pas retirer une valeur d'ENUM sans recréer le type.
    op.execute("ALTER TABLE channels ALTER COLUMN platform TYPE VARCHAR(32) USING platform::text")
    op.execute("DROP TYPE channel_platform")
    op.execute("CREATE TYPE channel_platform AS ENUM ('YOUTUBE')")
    op.execute(
        "ALTER TABLE channels ALTER COLUMN platform TYPE channel_platform "
        "USING platform::channel_platform"
    )
