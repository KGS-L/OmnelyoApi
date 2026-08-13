"""multi-format publication assets

Revision ID: 20260813_0015
Revises: 20260813_0014
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260813_0015"
down_revision = "20260813_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    asset_type = postgresql.ENUM("image", name="media_asset_type", create_type=False)
    asset_type.create(op.get_bind(), checkfirst=True)
    publication_format = postgresql.ENUM(
        "short_video", "standard_video", "photo", "carousel",
        name="publication_format", create_type=False,
    )
    publication_format.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "publications",
        sa.Column("format", publication_format, server_default="short_video", nullable=False),
    )
    op.create_index("ix_publications_format", "publications", ["format"])
    op.alter_column("publications", "video_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", asset_type, nullable=False),
        sa.Column("storage_key", sa.String(1024), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("workspace_id", "type", "retention_expires_at"):
        op.create_index(f"ix_media_assets_{column}", "media_assets", [column])
    op.create_table(
        "publication_media_assets",
        sa.Column("publication_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("publications.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("media_assets.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 0", name="ck_publication_media_position"),
        sa.UniqueConstraint("publication_id", "position", name="uq_publication_media_position"),
        sa.UniqueConstraint("publication_id", "asset_id", name="uq_publication_media_asset"),
    )


def downgrade() -> None:
    op.drop_table("publication_media_assets")
    op.drop_table("media_assets")
    op.alter_column("publications", "video_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_index("ix_publications_format", table_name="publications")
    op.drop_column("publications", "format")
    postgresql.ENUM(name="publication_format").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="media_asset_type").drop(op.get_bind(), checkfirst=True)
