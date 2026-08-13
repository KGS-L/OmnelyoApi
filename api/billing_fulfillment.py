"""Application idempotente des achats confirmés aux droits ShortPilot."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.credit_service import CreditService
from api.models import (
    BillingPlan,
    CreditAccount,
    FulfillmentStatus,
    PaymentFulfillment,
    PaymentIntent,
    ProductType,
    ProviderPriceMapping,
    WorkspaceEntitlement,
)


class FulfillmentError(ValueError):
    pass


class BillingFulfillmentService:
    def apply_payment(
        self, db: Session, intent: PaymentIntent, provider_payment_id: str
    ) -> PaymentFulfillment:
        payment_id = provider_payment_id.strip()
        if not payment_id:
            raise FulfillmentError("Identifiant de paiement requis pour attribuer l'achat.")
        existing = db.scalar(select(PaymentFulfillment).where(
            PaymentFulfillment.provider == intent.provider,
            PaymentFulfillment.provider_payment_id == payment_id,
        ))
        if existing is not None:
            return existing

        credits = CreditService()
        entitlement, account = credits.ensure_workspace(db, intent.workspace_id)
        entitlement = db.scalar(select(WorkspaceEntitlement).where(
            WorkspaceEntitlement.workspace_id == intent.workspace_id
        ).with_for_update())
        account = db.scalar(select(CreditAccount).where(
            CreditAccount.id == account.id
        ).with_for_update())
        if entitlement is None or account is None:
            raise FulfillmentError("Compte de droits introuvable.")

        plan_code = None
        granted = 0
        now = datetime.now(timezone.utc)
        if intent.product_type is ProductType.SUBSCRIPTION:
            plan_code = intent.purchase_code.removesuffix("_MONTHLY")
            plan = db.get(BillingPlan, plan_code)
            if plan is None or not plan.active:
                raise FulfillmentError("Plan acheté introuvable ou inactif.")
            current_end = _aware(entitlement.period_end)
            start = current_end if entitlement.plan_code == plan_code and current_end > now else now
            entitlement.plan_code = plan_code
            entitlement.period_start = start
            entitlement.period_end = start + timedelta(days=30)
            granted = plan.monthly_credits
        else:
            mapping = db.scalar(select(ProviderPriceMapping).where(
                ProviderPriceMapping.provider == intent.provider,
                ProviderPriceMapping.external_product_id == intent.external_product_id,
                ProviderPriceMapping.active.is_(True),
            ))
            if mapping is None or not mapping.credits_granted:
                raise FulfillmentError("La quantité de crédits de cette recharge n'est pas configurée.")
            granted = mapping.credits_granted

        fulfillment = PaymentFulfillment(
            payment_intent_id=intent.id,
            workspace_id=intent.workspace_id,
            provider=intent.provider,
            provider_payment_id=payment_id,
            purchase_code=intent.purchase_code,
            plan_code=plan_code,
            credits_granted=granted,
            status=FulfillmentStatus.APPLIED,
        )
        db.add(fulfillment)
        db.flush()
        credits.grant(
            db, account, granted,
            f"payment:{intent.provider.value}:{payment_id}",
            f"Crédits attribués après paiement {intent.purchase_code}",
            entitlement.period_end + timedelta(days=30) if plan_code else now + timedelta(days=365),
        )
        return fulfillment

    def record_refund(
        self, db: Session, intent: PaymentIntent, provider_payment_id: str
    ) -> PaymentFulfillment | None:
        fulfillment = db.scalar(select(PaymentFulfillment).where(
            PaymentFulfillment.provider == intent.provider,
            PaymentFulfillment.provider_payment_id == provider_payment_id,
        ).with_for_update())
        if fulfillment is not None and fulfillment.status is FulfillmentStatus.APPLIED:
            fulfillment.status = FulfillmentStatus.REFUNDED
            fulfillment.refunded_at = datetime.now(timezone.utc)
        return fulfillment

    def expire_subscription(
        self, db: Session, workspace_id, external_subscription_id: str
    ) -> WorkspaceEntitlement:
        credits = CreditService()
        entitlement, account = credits.ensure_workspace(db, workspace_id)
        entitlement = db.scalar(select(WorkspaceEntitlement).where(
            WorkspaceEntitlement.workspace_id == workspace_id
        ).with_for_update())
        if entitlement is None:
            raise FulfillmentError("Droits du workspace introuvables.")
        if entitlement.plan_code == "FREE":
            return entitlement
        plan = db.get(BillingPlan, "FREE")
        if plan is None or not plan.active:
            raise FulfillmentError("Plan Gratuit introuvable ou inactif.")
        now = datetime.now(timezone.utc)
        entitlement.plan_code = "FREE"
        entitlement.period_start = now
        entitlement.period_end = now + timedelta(days=30)
        credits.grant(
            db, account, plan.monthly_credits,
            f"subscription-expired:{external_subscription_id}",
            "Crédits du plan Gratuit après expiration de l'abonnement",
            entitlement.period_end + timedelta(days=30),
        )
        return entitlement


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
