"""channels, videos, jobs and publications

Revision ID: 20260813_0002
Revises: 20260813_0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260813_0002"
down_revision = "20260813_0001"
branch_labels = None
depends_on = None

channel_platform = postgresql.ENUM("YOUTUBE", name="channel_platform", create_type=False)
channel_status = postgresql.ENUM("ACTIVE", "DISCONNECTED", "REVOKED", name="channel_status", create_type=False)
video_status = postgresql.ENUM("UPLOADED", "QUEUED", "PROCESSING", "READY", "FAILED", name="video_status", create_type=False)
job_type = postgresql.ENUM("INGEST", "PROCESS", "RENDER", "PUBLISH", name="job_type", create_type=False)
job_status = postgresql.ENUM("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED", name="job_status", create_type=False)
publication_visibility = postgresql.ENUM("PRIVATE", "UNLISTED", "PUBLIC", name="publication_visibility", create_type=False)
publication_status = postgresql.ENUM("DRAFT", "SCHEDULED", "PUBLISHING", "PUBLISHED", "FAILED", "CANCELLED", name="publication_status", create_type=False)


def upgrade():
    for enum_type in (channel_platform, channel_status, video_status, job_type, job_status, publication_visibility, publication_status):
        enum_type.create(op.get_bind())

    op.create_table(
        "channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", channel_platform, nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("handle", sa.String(255)),
        sa.Column("avatar_url", sa.String(2048)),
        sa.Column("status", channel_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("platform", "external_id", name="uq_channels_platform_external_id"),
    )
    op.create_index("ix_channels_workspace_id", "channels", ["workspace_id"])

    op.create_table(
        "videos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255)),
        sa.Column("source_url", sa.String(2048)),
        sa.Column("storage_key", sa.String(1024)),
        sa.Column("mime_type", sa.String(127)),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("status", video_status, nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_videos_workspace_id", "videos", ["workspace_id"])
    op.create_index("ix_videos_status", "videos", ["status"])

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("videos.id", ondelete="CASCADE")),
        sa.Column("type", job_type, nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON()),
        sa.Column("result", sa.JSON()),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("progress >= 0 AND progress <= 100", name="ck_jobs_progress"),
        sa.CheckConstraint("attempts >= 0", name="ck_jobs_attempts"),
        sa.CheckConstraint("max_attempts > 0", name="ck_jobs_max_attempts"),
    )
    op.create_index("ix_jobs_workspace_id", "jobs", ["workspace_id"])
    op.create_index("ix_jobs_video_id", "jobs", ["video_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])

    op.create_table(
        "publications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("video_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("external_id", sa.String(255)),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("visibility", publication_visibility, nullable=False),
        sa.Column("status", publication_status, nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("channel_id", "external_id", name="uq_publications_channel_external_id"),
    )
    for column in ("workspace_id", "video_id", "channel_id", "job_id", "status", "scheduled_at"):
        op.create_index(f"ix_publications_{column}", "publications", [column])


def downgrade():
    op.drop_table("publications")
    op.drop_table("jobs")
    op.drop_table("videos")
    op.drop_table("channels")
    for enum_type in reversed((channel_platform, channel_status, video_status, job_type, job_status, publication_visibility, publication_status)):
        enum_type.drop(op.get_bind())
