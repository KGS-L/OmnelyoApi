"""partner profiles, promo codes, referrals and commissions

Revision ID: 20260813_0016
Revises: 20260813_0015
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260813_0016"
down_revision = "20260813_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    partner_status = postgresql.ENUM("pending", "active", "suspended", "closed", name="partner_status", create_type=False)
    commission_status = postgresql.ENUM("pending", "available", "paid", "canceled", name="partner_commission_status", create_type=False)
    payout_status = postgresql.ENUM("pending", "processing", "paid", "failed", name="partner_payout_status", create_type=False)
    for enum_type in (partner_status, commission_status, payout_status):
        enum_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "partner_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("status", partner_status, server_default="pending", nullable=False),
        sa.Column("commission_bps", sa.Integer(), server_default="2000", nullable=False),
        sa.Column("commission_months", sa.Integer(), server_default="12", nullable=False),
        sa.Column("payout_threshold_minor", sa.Integer(), server_default="25000", nullable=False),
        sa.Column("payout_currency", sa.String(3), server_default="XOF", nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("commission_bps > 0 AND commission_bps <= 10000", name="ck_partner_commission_bps"),
        sa.CheckConstraint("commission_months > 0", name="ck_partner_commission_months"),
        sa.CheckConstraint("payout_threshold_minor > 0", name="ck_partner_payout_threshold"),
    )
    for column in ("user_id", "status"):
        op.create_index(f"ix_partner_profiles_{column}", "partner_profiles", [column])

    op.create_table(
        "promo_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("partner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("discount_bps", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("discount_cycles", sa.Integer(), server_default="3", nullable=False),
        sa.Column("eligible_plan_codes", postgresql.JSONB(), server_default='["CREATOR", "PRO"]', nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("max_redemptions", sa.Integer()),
        sa.Column("redemption_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("discount_bps > 0 AND discount_bps <= 10000", name="ck_promo_discount_bps"),
        sa.CheckConstraint("discount_cycles > 0", name="ck_promo_discount_cycles"),
        sa.CheckConstraint("max_redemptions IS NULL OR max_redemptions > 0", name="ck_promo_max_redemptions"),
    )
    for column in ("partner_id", "code", "ends_at", "active"):
        op.create_index(f"ix_promo_codes_{column}", "promo_codes", [column])

    op.create_table(
        "referral_attributions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("partner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("promo_code_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("promo_codes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("attributed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("converted_at", sa.DateTime(timezone=True)),
    )
    for column in ("partner_id", "promo_code_id", "workspace_id", "expires_at", "converted_at"):
        op.create_index(f"ix_referral_attributions_{column}", "referral_attributions", [column])

    op.add_column("payment_intents", sa.Column("original_amount_minor", sa.Integer(), nullable=True))
    op.add_column("payment_intents", sa.Column("discount_amount_minor", sa.Integer(), server_default="0", nullable=False))
    op.add_column("payment_intents", sa.Column("promo_code_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("promo_codes.id", ondelete="RESTRICT")))
    op.add_column("payment_intents", sa.Column("referral_attribution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("referral_attributions.id", ondelete="RESTRICT")))
    op.add_column("payment_intents", sa.Column("promo_code_snapshot", sa.String(32)))
    op.add_column("payment_intents", sa.Column("discount_bps_snapshot", sa.Integer()))
    op.add_column("payment_intents", sa.Column("discount_cycles_snapshot", sa.Integer()))
    op.execute("UPDATE payment_intents SET original_amount_minor = expected_amount_minor WHERE original_amount_minor IS NULL")
    op.alter_column("payment_intents", "original_amount_minor", nullable=False)
    op.create_index("ix_payment_intents_promo_code_id", "payment_intents", ["promo_code_id"])
    op.create_index("ix_payment_intents_referral_attribution_id", "payment_intents", ["referral_attribution_id"])

    op.create_table(
        "partner_payouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("partner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("status", payout_status, server_default="pending", nullable=False),
        sa.Column("external_reference", sa.String(255), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount_minor > 0", name="ck_partner_payout_amount"),
    )
    for column in ("partner_id", "status"):
        op.create_index(f"ix_partner_payouts_{column}", "partner_payouts", [column])

    op.create_table(
        "partner_commissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("partner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attribution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("referral_attributions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("payment_intent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_intents.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("payout_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("partner_payouts.id", ondelete="SET NULL")),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("net_revenue_minor", sa.Integer(), nullable=False),
        sa.Column("commission_bps", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("status", commission_status, server_default="pending", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("net_revenue_minor >= 0", name="ck_partner_commission_net_revenue"),
        sa.CheckConstraint("amount_minor >= 0", name="ck_partner_commission_amount"),
        sa.CheckConstraint("commission_bps > 0 AND commission_bps <= 10000", name="ck_partner_commission_rate"),
    )
    for column in ("partner_id", "attribution_id", "payment_intent_id", "payout_id", "status", "available_at"):
        op.create_index(f"ix_partner_commissions_{column}", "partner_commissions", [column])

    op.execute("UPDATE billing_plans SET publications_monthly_limit = 100 WHERE code = 'CREATOR'")
    op.execute("UPDATE billing_plans SET publications_monthly_limit = 500 WHERE code = 'PRO'")


def downgrade() -> None:
    op.execute("UPDATE billing_plans SET publications_monthly_limit = 120 WHERE code = 'CREATOR'")
    op.execute("UPDATE billing_plans SET publications_monthly_limit = 800 WHERE code = 'PRO'")
    for table in ("partner_commissions", "partner_payouts", "referral_attributions", "promo_codes", "partner_profiles"):
        if table == "referral_attributions":
            for column in ("referral_attribution_id", "promo_code_id"):
                op.drop_index(f"ix_payment_intents_{column}", table_name="payment_intents")
            for column in ("discount_cycles_snapshot", "discount_bps_snapshot", "promo_code_snapshot", "referral_attribution_id", "promo_code_id", "discount_amount_minor", "original_amount_minor"):
                op.drop_column("payment_intents", column)
        op.drop_table(table)
    postgresql.ENUM(name="partner_payout_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="partner_commission_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="partner_status").drop(op.get_bind(), checkfirst=True)
