"""source and clip video hierarchy

Revision ID: 20260813_0005
Revises: 20260813_0004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260813_0005"
down_revision = "20260813_0004"
branch_labels = None
depends_on = None

video_kind = postgresql.ENUM("SOURCE", "CLIP", name="video_kind", create_type=False)


def upgrade():
    video_kind.create(op.get_bind())
    op.add_column("videos", sa.Column("parent_video_id", postgresql.UUID(as_uuid=True)))
    op.add_column(
        "videos",
        sa.Column("kind", video_kind, server_default="SOURCE", nullable=False),
    )
    op.add_column("videos", sa.Column("sequence_order", sa.Integer()))
    op.create_foreign_key(
        "fk_videos_parent_video_id",
        "videos",
        "videos",
        ["parent_video_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_videos_parent_video_id", "videos", ["parent_video_id"])
    op.create_index("ix_videos_kind", "videos", ["kind"])
    op.create_unique_constraint(
        "uq_videos_parent_sequence", "videos", ["parent_video_id", "sequence_order"]
    )
    op.create_check_constraint(
        "ck_videos_kind_parent",
        "videos",
        "(kind = 'SOURCE' AND parent_video_id IS NULL AND sequence_order IS NULL) OR "
        "(kind = 'CLIP' AND parent_video_id IS NOT NULL AND sequence_order > 0)",
    )


def downgrade():
    op.drop_constraint("ck_videos_kind_parent", "videos", type_="check")
    op.drop_constraint("uq_videos_parent_sequence", "videos", type_="unique")
    op.drop_index("ix_videos_kind", table_name="videos")
    op.drop_index("ix_videos_parent_video_id", table_name="videos")
    op.drop_constraint("fk_videos_parent_video_id", "videos", type_="foreignkey")
    op.drop_column("videos", "sequence_order")
    op.drop_column("videos", "kind")
    op.drop_column("videos", "parent_video_id")
    video_kind.drop(op.get_bind())
