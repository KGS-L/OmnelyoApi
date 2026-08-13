"""provider-neutral billing models (payment_intents, provider_events, subscriptions, mappings)

Revision ID: 20260813_0012
Revises: 20260813_0011
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260813_0012"
down_revision = "20260813_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enums (scoped per-table to avoid cross-table coupling)
    billing_provider = postgresql.ENUM("dodo", "moneyfusion", name="billing_provider", create_type=False)
    billing_provider.create(op.get_bind(), checkfirst=True)

    billing_product_type = postgresql.ENUM("subscription", "credits", name="billing_product_type", create_type=False)
    billing_product_type.create(op.get_bind(), checkfirst=True)

    payment_intent_status = postgresql.ENUM(
        "pending", "succeeded", "failed", "canceled", "refunded", name="payment_intent_status", create_type=False
    )
    payment_intent_status.create(op.get_bind(), checkfirst=True)

    provider_events_provider = postgresql.ENUM("dodo", "moneyfusion", name="provider_events_provider", create_type=False)
    provider_events_provider.create(op.get_bind(), checkfirst=True)

    subscriptions_provider = postgresql.ENUM("dodo", "moneyfusion", name="subscriptions_provider", create_type=False)
    subscriptions_provider.create(op.get_bind(), checkfirst=True)

    subscription_status = postgresql.ENUM(
        "active", "past_due", "canceled", "expired", "on_hold", name="subscription_status", create_type=False
    )
    subscription_status.create(op.get_bind(), checkfirst=True)

    price_mappings_provider = postgresql.ENUM("dodo", "moneyfusion", name="price_mappings_provider", create_type=False)
    price_mappings_provider.create(op.get_bind(), checkfirst=True)

    price_mappings_product_type = postgresql.ENUM("subscription", "credits", name="price_mappings_product_type", create_type=False)
    price_mappings_product_type.create(op.get_bind(), checkfirst=True)

    price_mappings_interval = postgresql.ENUM("month", "year", name="price_mappings_interval", create_type=False)
    price_mappings_interval.create(op.get_bind(), checkfirst=True)

    # Tables
    op.create_table(
        "payment_intents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("provider", billing_provider, nullable=False),
        sa.Column("purchase_code", sa.String(length=64), nullable=False, index=True),
        sa.Column("product_type", billing_product_type, nullable=False),
        sa.Column("expected_amount_minor", sa.Integer(), nullable=False),
        sa.Column("expected_currency", sa.String(length=3), nullable=False),
        sa.Column("external_product_id", sa.String(length=255), nullable=True),
        sa.Column("external_price_id", sa.String(length=255), nullable=True),
        sa.Column("customer_email", sa.String(length=320), nullable=True),
        # Canonical identifiers
        sa.Column("checkout_session_id", sa.String(length=255), nullable=True),
        sa.Column("payment_id", sa.String(length=255), nullable=True),
        sa.Column("subscription_id", sa.String(length=255), nullable=True),
        sa.Column("customer_id", sa.String(length=255), nullable=True),
        sa.Column("checkout_url", sa.String(length=2048), nullable=True),
        sa.Column("status", payment_intent_status, nullable=False, server_default="pending"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "checkout_session_id", name="uq_payment_intents_provider_checkout_session"),
        sa.UniqueConstraint("provider", "payment_id", name="uq_payment_intents_provider_payment"),
        sa.UniqueConstraint("workspace_id", "provider", "idempotency_key", name="uq_payment_intents_ws_provider_idem"),
    )
    op.create_index("ix_payment_intents_created_at", "payment_intents", ["created_at"])
    op.create_index("ix_payment_intents_status", "payment_intents", ["status"])
    op.create_index("ix_payment_intents_workspace", "payment_intents", ["workspace_id"])

    # Provider event status enum
    provider_event_status = postgresql.ENUM("received", "processed", "deferred", "failed", name="provider_event_status", create_type=False)
    provider_event_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "provider_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider", provider_events_provider, nullable=False),
        sa.Column("external_event_id", sa.String(length=255), nullable=False, index=True),
        sa.Column("event_type", sa.String(length=64), nullable=False, index=True),
        # Canonical identifiers
        sa.Column("checkout_session_id", sa.String(length=255), nullable=True, index=True),
        sa.Column("payment_id", sa.String(length=255), nullable=True, index=True),
        sa.Column("subscription_id", sa.String(length=255), nullable=True, index=True),
        sa.Column("customer_id", sa.String(length=255), nullable=True, index=True),
        sa.Column("provider_created_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("status", provider_event_status, nullable=False, server_default="received"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=255), nullable=True),
        sa.UniqueConstraint("provider", "external_event_id", name="uq_provider_events_provider_event"),
    )
    op.create_index("ix_provider_events_processed_at", "provider_events", ["processed_at"])

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("provider", subscriptions_provider, nullable=False),
        sa.Column("external_subscription_id", sa.String(length=255), nullable=False),
        sa.Column("internal_plan_code", sa.String(length=64), nullable=False, index=True),
        sa.Column("status", subscription_status, nullable=False, server_default="active"),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_payment_id", sa.String(length=255), nullable=True, index=True),
        sa.Column("latest_checkout_session_id", sa.String(length=255), nullable=True, index=True),
        sa.Column("customer_id", sa.String(length=255), nullable=True, index=True),
        sa.Column("last_provider_event_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "external_subscription_id", name="uq_subscriptions_provider_external"),
    )
    op.create_index("ix_subscriptions_workspace", "subscriptions", ["workspace_id"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])

    op.create_table(
        "provider_price_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider", price_mappings_provider, nullable=False),
        sa.Column("internal_plan_code", sa.String(length=64), nullable=False, index=True),
        sa.Column("product_type", price_mappings_product_type, nullable=False),
        sa.Column("interval", price_mappings_interval, nullable=True),
        sa.Column("external_product_id", sa.String(length=255), nullable=False),
        sa.Column("external_price_id", sa.String(length=255), nullable=True),
        sa.Column("expected_amount_minor", sa.Integer(), nullable=False),
        sa.Column("expected_currency", sa.String(length=3), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("provider", "internal_plan_code", "interval", name="uq_provider_price_mappings_unique"),
    )
    op.create_index("ix_provider_price_mappings_created_at", "provider_price_mappings", ["created_at"])
    op.create_index("ix_provider_price_mappings_active", "provider_price_mappings", ["active"])


def downgrade() -> None:
    op.drop_table("provider_price_mappings")
    op.drop_table("subscriptions")
    op.drop_table("provider_events")
    op.drop_table("payment_intents")

    # Drop enums
    for enum_name in [
        "provider_event_status",
        "price_mappings_interval",
        "price_mappings_product_type",
        "price_mappings_provider",
        "subscription_status",
        "subscriptions_provider",
        "provider_events_provider",
        "payment_intent_status",
        "billing_product_type",
        "billing_provider",
    ]:
        try:
            postgresql.ENUM(name=enum_name).drop(op.get_bind(), checkfirst=True)
        except Exception:
            pass
