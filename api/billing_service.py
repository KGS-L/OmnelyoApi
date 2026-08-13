from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.billing_providers.base import (
    CheckoutRequest,
    PaymentProvider,
    PortalRequest,
    ProviderPayloadError,
    ProviderSignatureError,
)
from api.models import (
    BillingInterval,
    PartnerCommission,
    PartnerCommissionStatus,
    PartnerProfile,
    PaymentIntent,
    PaymentIntentStatus,
    Provider,
    ProviderEvent,
    ProviderEventStatus,
    ProviderPriceMapping,
    PromoCode,
    ReferralAttribution,
    Subscription,
    SubscriptionStatus,
)
from api.partner_service import PartnerService
from api.billing_fulfillment import BillingFulfillmentService


class SignatureError(Exception):
    pass


class InvalidProviderPayload(Exception):
    pass


class ValidationFailure(Exception):
    pass


class CorrelationDeferred(Exception):
    pass


PROVIDERS = {"dodo": Provider.DODO, "moneyfusion": Provider.MONEYFUSION}
SUBSCRIPTION_STATUSES = {
    "subscription.active": SubscriptionStatus.ACTIVE,
    "subscription.renewed": SubscriptionStatus.ACTIVE,
    "subscription.past_due": SubscriptionStatus.PAST_DUE,
    "subscription.on_hold": SubscriptionStatus.ON_HOLD,
    "subscription.failed": SubscriptionStatus.PAST_DUE,
    "subscription.cancelled": SubscriptionStatus.CANCELED,
    "subscription.canceled": SubscriptionStatus.CANCELED,
    "subscription.expired": SubscriptionStatus.EXPIRED,
}


class BillingPGService:
    def __init__(self, provider: PaymentProvider) -> None:
        try:
            self.provider_enum = PROVIDERS[provider.name]
        except KeyError as exc:
            raise ValueError("Fournisseur de paiement non supporté.") from exc
        self.provider = provider

    @staticmethod
    def _mapping_key(purchase_code: str) -> tuple[str, BillingInterval | None]:
        values = {
            "CREATOR_MONTHLY": ("CREATOR", BillingInterval.MONTH),
            "PRO_MONTHLY": ("PRO", BillingInterval.MONTH),
            "TOPUP": ("TOPUP", None),
        }
        try:
            return values[purchase_code.strip().upper()]
        except KeyError as exc:
            raise ValueError("Code d'achat inconnu.") from exc

    def _find_mapping(self, db: Session, purchase_code: str) -> ProviderPriceMapping:
        plan, interval = self._mapping_key(purchase_code)
        interval_clause = (
            ProviderPriceMapping.interval.is_(None)
            if interval is None
            else ProviderPriceMapping.interval == interval
        )
        mapping = db.scalar(
            select(ProviderPriceMapping).where(
                ProviderPriceMapping.provider == self.provider_enum,
                ProviderPriceMapping.internal_plan_code == plan,
                interval_clause,
                ProviderPriceMapping.active.is_(True),
            )
        )
        if mapping is None:
            raise ValueError("Aucun mappage produit/prix actif pour ce fournisseur.")
        return mapping

    def start_checkout(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        purchase_code: str,
        customer_email: str | None,
        idempotency_key: str,
        customer_name: str | None = None,
        customer_phone: str | None = None,
        promo_code: str | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> PaymentIntent:
        mapping = self._find_mapping(db, purchase_code)
        if self.provider_enum == Provider.MONEYFUSION and mapping.product_type.value == "subscription":
            raise ValueError("MoneyFusion est limité aux achats ponctuels; utilise Dodo pour un abonnement.")
        promo_quote = None
        attribution = None
        if promo_code:
            plan_code = self._mapping_key(purchase_code)[0]
            if mapping.product_type.value != "subscription":
                raise ValueError("Les codes partenaires sont réservés aux abonnements Creator et Pro.")
            partner_service = PartnerService()
            promo_quote = partner_service.quote(
                db, promo_code, plan_code, mapping.expected_amount_minor
            )
            if actor_user_id is None:
                raise ValueError("L'utilisateur du checkout est requis avec un code partenaire.")
            partner_service.reject_self_referral(db, promo_quote.partner_id, actor_user_id)
            attribution = partner_service.attribute(db, workspace_id, promo_quote)
        existing = db.scalar(
            select(PaymentIntent).where(
                PaymentIntent.workspace_id == workspace_id,
                PaymentIntent.provider == self.provider_enum,
                PaymentIntent.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            requested_code = promo_quote.code if promo_quote else None
            if existing.purchase_code != purchase_code.strip().upper() or existing.promo_code_snapshot != requested_code:
                raise ValueError("Cette clé d'idempotence a déjà été utilisée avec un autre achat.")
            return existing

        final_amount = promo_quote.final_amount_minor if promo_quote else mapping.expected_amount_minor

        intent = PaymentIntent(
            workspace_id=workspace_id,
            provider=self.provider_enum,
            purchase_code=purchase_code.strip().upper(),
            product_type=mapping.product_type,
            expected_amount_minor=final_amount,
            original_amount_minor=mapping.expected_amount_minor,
            discount_amount_minor=promo_quote.discount_amount_minor if promo_quote else 0,
            expected_currency=mapping.expected_currency.upper(),
            external_product_id=mapping.external_product_id,
            external_price_id=mapping.external_price_id,
            customer_email=customer_email.strip().lower() if customer_email else None,
            promo_code_id=promo_quote.promo_code_id if promo_quote else None,
            referral_attribution_id=attribution.id if attribution else None,
            promo_code_snapshot=promo_quote.code if promo_quote else None,
            discount_bps_snapshot=promo_quote.discount_bps if promo_quote else None,
            discount_cycles_snapshot=promo_quote.discount_cycles if promo_quote else None,
            idempotency_key=idempotency_key,
            status=PaymentIntentStatus.PENDING,
        )
        db.add(intent)
        db.flush()
        try:
            result = self.provider.create_checkout(
                CheckoutRequest(
                    workspace_id=workspace_id,
                    purchase_code=intent.purchase_code,
                    customer_email=intent.customer_email,
                    customer_name=customer_name,
                    customer_phone=customer_phone,
                    idempotency_key=idempotency_key,
                    external_product_id=mapping.external_product_id,
                    expected_amount_minor=final_amount,
                    expected_currency=mapping.expected_currency.upper(),
                    discount_codes=[promo_quote.code] if promo_quote and self.provider_enum == Provider.DODO else [],
                    metadata={
                        "payment_intent_id": str(intent.id),
                        **({"promo_code": promo_quote.code} if promo_quote else {}),
                    },
                )
            )
            intent.checkout_session_id = result.checkout_session_id
            intent.checkout_url = result.checkout_url
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(intent)
        return intent

    def _correlate(self, db: Session, parsed) -> PaymentIntent | None:
        local_id = (parsed.metadata or {}).get("payment_intent_id")
        if local_id:
            try:
                intent = db.get(PaymentIntent, uuid.UUID(local_id))
            except (ValueError, TypeError):
                intent = None
            if intent is not None and intent.provider == self.provider_enum:
                return intent
        for column, value in (
            (PaymentIntent.checkout_session_id, parsed.checkout_session_id),
            (PaymentIntent.payment_id, parsed.payment_id),
            (PaymentIntent.subscription_id, parsed.subscription_id),
        ):
            if value:
                intent = db.scalar(
                    select(PaymentIntent).where(
                        PaymentIntent.provider == self.provider_enum, column == value
                    )
                )
                if intent is not None:
                    return intent
        return None

    def _validate_payment(self, intent: PaymentIntent, parsed) -> None:
        amount, currency = parsed.amount_minor, parsed.currency
        product_id, price_id = parsed.product_id, parsed.price_id
        if parsed.payment_id and (
            amount is None
            or currency is None
            or (self.provider_enum == Provider.DODO and product_id is None)
            or (intent.external_price_id is not None and price_id is None)
        ):
            snapshot = self.provider.retrieve_payment(parsed.payment_id)
            amount = amount if amount is not None else snapshot.amount_minor
            currency = currency if currency is not None else snapshot.currency
            product_id = product_id if product_id is not None else snapshot.product_id
            price_id = price_id if price_id is not None else snapshot.price_id
        if amount is None or amount != intent.expected_amount_minor:
            raise ValidationFailure("Montant de paiement absent ou incorrect.")
        if currency is None or currency.upper() != intent.expected_currency.upper():
            raise ValidationFailure("Devise de paiement absente ou incorrecte.")
        if self.provider_enum == Provider.DODO:
            if intent.external_product_id and product_id != intent.external_product_id:
                raise ValidationFailure("Produit de paiement absent ou incorrect.")
            if intent.external_price_id and price_id != intent.external_price_id:
                raise ValidationFailure("Prix de paiement absent ou incorrect.")

    @staticmethod
    def _mark_failed(db: Session, event: ProviderEvent, code: str, message: str) -> None:
        event.status = ProviderEventStatus.FAILED
        event.error_code = code
        event.error_message = message[:255]
        db.commit()

    @staticmethod
    def _apply_partner_payment(db: Session, intent: PaymentIntent, event_type: str) -> None:
        if intent.referral_attribution_id is None:
            return
        commission = db.scalar(select(PartnerCommission).where(
            PartnerCommission.payment_intent_id == intent.id
        ))
        if event_type == "refund.succeeded":
            if commission is not None:
                commission.status = PartnerCommissionStatus.CANCELED
            return
        if event_type != "payment.succeeded" or commission is not None:
            return
        attribution = db.get(ReferralAttribution, intent.referral_attribution_id)
        if attribution is None:
            raise ValidationFailure("Attribution partenaire introuvable.")
        partner = db.get(PartnerProfile, attribution.partner_id)
        promo = db.get(PromoCode, attribution.promo_code_id)
        if partner is None or promo is None:
            raise ValidationFailure("Configuration partenaire introuvable.")
        now = datetime.now(timezone.utc)
        attribution.converted_at = attribution.converted_at or now
        promo.redemption_count += 1
        amount = intent.expected_amount_minor * partner.commission_bps // 10_000
        db.add(PartnerCommission(
            partner_id=partner.id,
            attribution_id=attribution.id,
            payment_intent_id=intent.id,
            currency=intent.expected_currency,
            net_revenue_minor=intent.expected_amount_minor,
            commission_bps=partner.commission_bps,
            amount_minor=amount,
            status=PartnerCommissionStatus.PENDING,
            available_at=now + timedelta(days=30),
        ))

    def process_webhook(self, db: Session, headers: Mapping[str, str], body: bytes) -> str:
        try:
            parsed = self.provider.verify_and_parse_webhook(headers, body)
        except ProviderSignatureError as exc:
            raise SignatureError(str(exc)) from exc
        except ProviderPayloadError as exc:
            raise InvalidProviderPayload(str(exc)) from exc

        event = ProviderEvent(
            provider=self.provider_enum,
            external_event_id=parsed.external_event_id,
            event_type=parsed.event_type,
            checkout_session_id=parsed.checkout_session_id,
            payment_id=parsed.payment_id,
            subscription_id=parsed.subscription_id,
            customer_id=parsed.customer_id,
            provider_created_at=parsed.provider_created_at,
            status=ProviderEventStatus.RECEIVED,
            payload=parsed.payload,
        )
        try:
            db.add(event)
            db.flush()
        except IntegrityError:
            db.rollback()
            return "duplicate"

        intent = self._correlate(db, parsed)
        if parsed.event_type.startswith(("payment.", "refund.", "subscription.")) and intent is None:
            event.status = ProviderEventStatus.DEFERRED
            event.error_code = "uncorrelated"
            event.error_message = "Aucun PaymentIntent local correspondant."
            db.commit()
            raise CorrelationDeferred(event.error_message)

        try:
            if parsed.event_type in {"payment.succeeded", "payment.failed", "refund.succeeded"}:
                self._validate_payment(intent, parsed)
                if parsed.event_type in {"payment.succeeded", "refund.succeeded"} and not parsed.payment_id:
                    raise ValidationFailure("Identifiant de paiement absent.")
                if parsed.payment_id:
                    intent.payment_id = parsed.payment_id
                intent.customer_id = parsed.customer_id or intent.customer_id
                intent.subscription_id = parsed.subscription_id or intent.subscription_id
                if parsed.event_type == "payment.succeeded":
                    intent.status = PaymentIntentStatus.SUCCEEDED
                    BillingFulfillmentService().apply_payment(
                        db, intent, parsed.payment_id
                    )
                elif parsed.event_type == "payment.failed" and intent.status == PaymentIntentStatus.PENDING:
                    intent.status = PaymentIntentStatus.FAILED
                elif parsed.event_type == "refund.succeeded":
                    intent.status = PaymentIntentStatus.REFUNDED
                    BillingFulfillmentService().record_refund(
                        db, intent, parsed.payment_id
                    )
                self._apply_partner_payment(db, intent, parsed.event_type)
            elif parsed.event_type in SUBSCRIPTION_STATUSES:
                if not parsed.subscription_id:
                    raise CorrelationDeferred("Identifiant d'abonnement absent.")
                status = SUBSCRIPTION_STATUSES[parsed.event_type]
                sub = db.scalar(
                    select(Subscription).where(
                        Subscription.provider == self.provider_enum,
                        Subscription.external_subscription_id == parsed.subscription_id,
                    )
                )
                if sub is None:
                    sub = Subscription(
                        workspace_id=intent.workspace_id,
                        provider=self.provider_enum,
                        external_subscription_id=parsed.subscription_id,
                        internal_plan_code=self._mapping_key(intent.purchase_code)[0],
                        status=status,
                    )
                    db.add(sub)
                elif not (
                    parsed.provider_created_at
                    and sub.last_provider_event_at
                    and parsed.provider_created_at < sub.last_provider_event_at
                ):
                    sub.status = status
                sub.customer_id = parsed.customer_id or sub.customer_id
                sub.latest_payment_id = parsed.payment_id or sub.latest_payment_id
                sub.latest_checkout_session_id = parsed.checkout_session_id or sub.latest_checkout_session_id
                sub.last_provider_event_at = parsed.provider_created_at or sub.last_provider_event_at
                intent.subscription_id = parsed.subscription_id
                if status is SubscriptionStatus.EXPIRED:
                    BillingFulfillmentService().expire_subscription(
                        db, intent.workspace_id, parsed.subscription_id
                    )
            event.status = ProviderEventStatus.PROCESSED
            event.processed_at = datetime.now(timezone.utc)
            db.commit()
            return "processed"
        except CorrelationDeferred:
            event.status = ProviderEventStatus.DEFERRED
            event.error_code = "uncorrelated"
            db.commit()
            raise
        except ValidationFailure as exc:
            self._mark_failed(db, event, "validation_failed", str(exc))
            raise
        except Exception as exc:
            self._mark_failed(db, event, "processing_failed", "Échec du traitement provider.")
            raise exc

    def create_portal_for_workspace(self, db: Session, workspace_id: uuid.UUID) -> str:
        sub = db.scalar(
            select(Subscription).where(
                Subscription.workspace_id == workspace_id,
                Subscription.provider == self.provider_enum,
                Subscription.customer_id.is_not(None),
            )
        )
        if sub is None or not sub.customer_id:
            raise ValueError("Aucun client de facturation trouvé pour ce workspace.")
        return self.provider.create_customer_portal(PortalRequest(customer_id=sub.customer_id)).url
