"""Modèles d'identité et de tenancy du backend PostgreSQL."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


class IdentityProvider(str, enum.Enum):
    EMAIL = "email"
    GOOGLE = "google"
    TELEGRAM = "telegram"


class WorkspaceRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class ChannelPlatform(str, enum.Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


class ChannelStatus(str, enum.Enum):
    ACTIVE = "active"
    DISCONNECTED = "disconnected"
    REVOKED = "revoked"


class SocialConnectionStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class VideoStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class VideoKind(str, enum.Enum):
    SOURCE = "source"
    CLIP = "clip"


class JobType(str, enum.Enum):
    INGEST = "ingest"
    PROCESS = "process"
    RENDER = "render"
    PUBLISH = "publish"


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PublicationStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PublicationVisibility(str, enum.Enum):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class TelegramConnectionStatus(str, enum.Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(120))
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (UniqueConstraint("provider", "provider_subject"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[IdentityProvider] = mapped_column(Enum(IdentityProvider, name="identity_provider"))
    provider_subject: Mapped[str] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    channels: Mapped[list["Channel"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    social_connections: Mapped[list["SocialConnection"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    videos: Mapped[list["Video"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    publications: Mapped[list["Publication"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[WorkspaceRole] = mapped_column(Enum(WorkspaceRole, name="workspace_role"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramConnection(Base):
    """Liaison vérifiée entre une identité web et un compte Telegram."""

    __tablename__ = "telegram_connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_telegram_connections_workspace_user"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[TelegramConnectionStatus] = mapped_column(
        Enum(TelegramConnectionStatus, name="telegram_connection_status"),
        default=TelegramConnectionStatus.ACTIVE,
    )
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditEvent(Base):
    """Trace append-only des mutations effectuées via l'API SaaS."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="SET NULL"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(32), index=True)
    resource_path: Mapped[str] = mapped_column(String(2048))
    request_id: Mapped[str] = mapped_column(String(128), index=True)
    response_status: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class SocialConnection(Base):
    """Credentials OAuth chiffrés d'un fournisseur pour un workspace."""

    __tablename__ = "social_connections"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "platform",
            "provider_account_id",
            name="uq_social_connections_workspace_provider_account",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[ChannelPlatform] = mapped_column(
        Enum(ChannelPlatform, name="channel_platform", create_type=False), index=True
    )
    provider_account_id: Mapped[str] = mapped_column(String(255))
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[SocialConnectionStatus] = mapped_column(
        Enum(SocialConnectionStatus, name="social_connection_status"),
        default=SocialConnectionStatus.ACTIVE,
        index=True,
    )
    provider_metadata: Mapped[dict | None] = mapped_column(JSON)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    workspace: Mapped[Workspace] = relationship(back_populates="social_connections")
    channels: Mapped[list["Channel"]] = relationship(back_populates="connection")


class Channel(Base):
    """Compte de diffusion connecté à un workspace."""

    __tablename__ = "channels"
    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_channels_platform_external_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("social_connections.id", ondelete="SET NULL"), index=True
    )
    platform: Mapped[ChannelPlatform] = mapped_column(
        Enum(ChannelPlatform, name="channel_platform")
    )
    external_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    handle: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[ChannelStatus] = mapped_column(
        Enum(ChannelStatus, name="channel_status"), default=ChannelStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    workspace: Mapped[Workspace] = relationship(back_populates="channels")
    connection: Mapped[SocialConnection | None] = relationship(back_populates="channels")
    publications: Mapped[list["Publication"]] = relationship(back_populates="channel")


class Video(Base):
    """Vidéo source ou artefact final appartenant à un workspace."""

    __tablename__ = "videos"
    __table_args__ = (
        UniqueConstraint("parent_video_id", "sequence_order", name="uq_videos_parent_sequence"),
        CheckConstraint(
            "(kind = 'SOURCE' AND parent_video_id IS NULL AND sequence_order IS NULL) OR "
            "(kind = 'CLIP' AND parent_video_id IS NOT NULL AND sequence_order > 0)",
            name="ck_videos_kind_parent",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    parent_video_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[VideoKind] = mapped_column(
        Enum(VideoKind, name="video_kind"), default=VideoKind.SOURCE, index=True
    )
    sequence_order: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    storage_key: Mapped[str | None] = mapped_column(String(1024))
    rendered_storage_key: Mapped[str | None] = mapped_column(String(1024))
    storage_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    rendered_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    mime_type: Mapped[str | None] = mapped_column(String(127))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    narration_text: Mapped[str | None] = mapped_column(Text)
    rendered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retention_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[VideoStatus] = mapped_column(
        Enum(VideoStatus, name="video_status"), default=VideoStatus.UPLOADED, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    workspace: Mapped[Workspace] = relationship(back_populates="videos")
    jobs: Mapped[list["Job"]] = relationship(back_populates="video")
    publications: Mapped[list["Publication"]] = relationship(back_populates="video")
    parent: Mapped["Video | None"] = relationship(
        remote_side="Video.id", back_populates="clips"
    )
    clips: Mapped[list["Video"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )


class Job(Base):
    """Unité de travail persistante et rejouable du pipeline vidéo."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_jobs_progress"),
        CheckConstraint("attempts >= 0", name="ck_jobs_attempts"),
        CheckConstraint("max_attempts > 0", name="ck_jobs_max_attempts"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[JobType] = mapped_column(Enum(JobType, name="job_type"))
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), default=JobStatus.QUEUED, index=True
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    payload: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    worker_id: Mapped[str | None] = mapped_column(String(255))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    workspace: Mapped[Workspace] = relationship(back_populates="jobs")
    video: Mapped[Video | None] = relationship(back_populates="jobs")
    publications: Mapped[list["Publication"]] = relationship(back_populates="job")


class Publication(Base):
    """Planification et résultat de diffusion d'une vidéo sur une chaîne."""

    __tablename__ = "publications"
    __table_args__ = (
        UniqueConstraint("channel_id", "external_id", name="uq_publications_channel_external_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("channels.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[PublicationVisibility] = mapped_column(
        Enum(PublicationVisibility, name="publication_visibility"),
        default=PublicationVisibility.PRIVATE,
    )
    status: Mapped[PublicationStatus] = mapped_column(
        Enum(PublicationStatus, name="publication_status"),
        default=PublicationStatus.DRAFT,
        index=True,
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    provider_response: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    workspace: Mapped[Workspace] = relationship(back_populates="publications")
    video: Mapped[Video] = relationship(back_populates="publications")
    channel: Mapped[Channel] = relationship(back_populates="publications")
    job: Mapped[Job | None] = relationship(back_populates="publications")


# --- Billing (provider-neutral, PostgreSQL source of truth) ---

class Provider(str, enum.Enum):
    DODO = "dodo"
    MONEYFUSION = "moneyfusion"


def _enum_values(enum_class):
    return [member.value for member in enum_class]


class ProductType(str, enum.Enum):
    SUBSCRIPTION = "subscription"
    CREDITS = "credits"


class BillingInterval(str, enum.Enum):
    MONTH = "month"
    YEAR = "year"


class PaymentIntentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"
    ON_HOLD = "on_hold"


class PaymentIntent(Base):
    __tablename__ = "payment_intents"
    __table_args__ = (
        UniqueConstraint("provider", "checkout_session_id", name="uq_payment_intents_provider_checkout_session"),
        UniqueConstraint("provider", "payment_id", name="uq_payment_intents_provider_payment"),
        UniqueConstraint("workspace_id", "provider", "idempotency_key", name="uq_payment_intents_ws_provider_idem"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    provider: Mapped[Provider] = mapped_column(Enum(Provider, name="billing_provider", values_callable=_enum_values))
    purchase_code: Mapped[str] = mapped_column(String(64), index=True)  # e.g., CREATOR_MONTHLY | PRO_MONTHLY | TOPUP
    product_type: Mapped[ProductType] = mapped_column(Enum(ProductType, name="billing_product_type", values_callable=_enum_values))
    expected_amount_minor: Mapped[int] = mapped_column(Integer)
    expected_currency: Mapped[str] = mapped_column(String(3))
    external_product_id: Mapped[str | None] = mapped_column(String(255))
    external_price_id: Mapped[str | None] = mapped_column(String(255))
    customer_email: Mapped[str | None] = mapped_column(String(320))
    # Canonical provider identifiers kept distinct
    checkout_session_id: Mapped[str | None] = mapped_column(String(255))
    payment_id: Mapped[str | None] = mapped_column(String(255))
    subscription_id: Mapped[str | None] = mapped_column(String(255))
    customer_id: Mapped[str | None] = mapped_column(String(255))
    checkout_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[PaymentIntentStatus] = mapped_column(
        Enum(PaymentIntentStatus, name="payment_intent_status", values_callable=_enum_values), default=PaymentIntentStatus.PENDING, index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProviderEventStatus(str, enum.Enum):
    RECEIVED = "received"
    PROCESSED = "processed"
    DEFERRED = "deferred"
    FAILED = "failed"


class ProviderEvent(Base):
    __tablename__ = "provider_events"
    __table_args__ = (
        UniqueConstraint("provider", "external_event_id", name="uq_provider_events_provider_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[Provider] = mapped_column(Enum(Provider, name="provider_events_provider", values_callable=_enum_values))
    external_event_id: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    # Canonical identifiers captured from the event for correlation and audit
    checkout_session_id: Mapped[str | None] = mapped_column(String(255), index=True)
    payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    subscription_id: Mapped[str | None] = mapped_column(String(255), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(255), index=True)
    provider_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[ProviderEventStatus] = mapped_column(
        Enum(ProviderEventStatus, name="provider_event_status", values_callable=_enum_values), default=ProviderEventStatus.RECEIVED, index=True
    )
    payload: Mapped[dict | None] = mapped_column(JSON)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(255))


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("provider", "external_subscription_id", name="uq_subscriptions_provider_external"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    provider: Mapped[Provider] = mapped_column(Enum(Provider, name="subscriptions_provider", values_callable=_enum_values))
    external_subscription_id: Mapped[str] = mapped_column(String(255))
    internal_plan_code: Mapped[str] = mapped_column(String(64), index=True)  # e.g., CREATOR | PRO
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status", values_callable=_enum_values), default=SubscriptionStatus.ACTIVE, index=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Track latest provider identifiers and ordering protection
    latest_payment_id: Mapped[str | None] = mapped_column(String(255), index=True)
    latest_checkout_session_id: Mapped[str | None] = mapped_column(String(255), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(255), index=True)
    last_provider_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProviderPriceMapping(Base):
    __tablename__ = "provider_price_mappings"
    __table_args__ = (
        UniqueConstraint("provider", "internal_plan_code", "interval", name="uq_provider_price_mappings_unique"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[Provider] = mapped_column(Enum(Provider, name="price_mappings_provider", values_callable=_enum_values))
    internal_plan_code: Mapped[str] = mapped_column(String(64), index=True)  # e.g., CREATOR, PRO, TOPUP
    product_type: Mapped[ProductType] = mapped_column(Enum(ProductType, name="price_mappings_product_type", values_callable=_enum_values))
    interval: Mapped[BillingInterval | None] = mapped_column(
        Enum(BillingInterval, name="price_mappings_interval", values_callable=_enum_values), nullable=True
    )
    external_product_id: Mapped[str] = mapped_column(String(255))
    external_price_id: Mapped[str | None] = mapped_column(String(255))
    # Server-known expected pricing for validation (minor units & 3-letter currency)
    expected_amount_minor: Mapped[int] = mapped_column(Integer)
    expected_currency: Mapped[str] = mapped_column(String(3))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --- Plans, entitlements and immutable credit accounting ---

class CreditEntryType(str, enum.Enum):
    GRANT = "grant"
    RESERVE = "reserve"
    CAPTURE = "capture"
    RELEASE = "release"
    REFUND = "refund"
    EXPIRE = "expire"
    ADJUSTMENT = "adjustment"


class CreditReservationStatus(str, enum.Enum):
    ACTIVE = "active"
    CAPTURED = "captured"
    RELEASED = "released"


class BillingPlan(Base):
    __tablename__ = "billing_plans"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    monthly_credits: Mapped[int] = mapped_column(Integer)
    social_connections_limit: Mapped[int] = mapped_column(Integer)
    workspaces_limit: Mapped[int] = mapped_column(Integer)
    members_per_workspace_limit: Mapped[int] = mapped_column(Integer)
    concurrent_jobs_limit: Mapped[int] = mapped_column(Integer)
    source_minutes_monthly_limit: Mapped[int] = mapped_column(Integer)
    publications_monthly_limit: Mapped[int] = mapped_column(Integer)
    storage_bytes_limit: Mapped[int] = mapped_column(BigInteger)
    retention_days: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WorkspaceEntitlement(Base):
    __tablename__ = "workspace_entitlements"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    plan_code: Mapped[str] = mapped_column(ForeignKey("billing_plans.code"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CreditAccount(Base):
    __tablename__ = "credit_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CreditReservation(Base):
    __tablename__ = "credit_reservations"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_credit_reservations_account_idem"),
        CheckConstraint("amount > 0", name="ck_credit_reservations_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_accounts.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), unique=True, index=True
    )
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[CreditReservationStatus] = mapped_column(
        Enum(CreditReservationStatus, name="credit_reservation_status", values_callable=_enum_values),
        default=CreditReservationStatus.ACTIVE,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreditLedgerEntry(Base):
    __tablename__ = "credit_ledger_entries"
    __table_args__ = (
        UniqueConstraint("account_id", "idempotency_key", name="uq_credit_ledger_account_idem"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_accounts.id", ondelete="CASCADE"), index=True
    )
    reservation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credit_reservations.id", ondelete="SET NULL"), index=True
    )
    entry_type: Mapped[CreditEntryType] = mapped_column(
        Enum(CreditEntryType, name="credit_entry_type", values_callable=_enum_values), index=True
    )
    amount: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(255))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class UsageMetric(str, enum.Enum):
    SOURCE_SECONDS = "source_seconds"
    PUBLICATIONS = "publications"


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "metric", "idempotency_key", name="uq_usage_events_ws_metric_idem"),
        CheckConstraint("quantity > 0", name="ck_usage_events_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    metric: Mapped[UsageMetric] = mapped_column(
        Enum(UsageMetric, name="usage_metric", values_callable=_enum_values), index=True
    )
    quantity: Mapped[int] = mapped_column(BigInteger)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
