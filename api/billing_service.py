from __future__ import annotations

import uuid
from datetime import datetime, timezone
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
    PaymentIntent,
    PaymentIntentStatus,
    Provider,
    ProviderEvent,
    ProviderEventStatus,
    ProviderPriceMapping,
    Subscription,
    SubscriptionStatus,
)


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
    ) -> PaymentIntent:
        mapping = self._find_mapping(db, purchase_code)
        if self.provider_enum == Provider.MONEYFUSION and mapping.product_type.value == "subscription":
            raise ValueError("MoneyFusion est limité aux achats ponctuels; utilise Dodo pour un abonnement.")
        existing = db.scalar(
            select(PaymentIntent).where(
                PaymentIntent.workspace_id == workspace_id,
                PaymentIntent.provider == self.provider_enum,
                PaymentIntent.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing

        intent = PaymentIntent(
            workspace_id=workspace_id,
            provider=self.provider_enum,
            purchase_code=purchase_code.strip().upper(),
            product_type=mapping.product_type,
            expected_amount_minor=mapping.expected_amount_minor,
            expected_currency=mapping.expected_currency.upper(),
            external_product_id=mapping.external_product_id,
            external_price_id=mapping.external_price_id,
            customer_email=customer_email.strip().lower() if customer_email else None,
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
                    expected_amount_minor=mapping.expected_amount_minor,
                    expected_currency=mapping.expected_currency.upper(),
                    metadata={"payment_intent_id": str(intent.id)},
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
                if parsed.payment_id:
                    intent.payment_id = parsed.payment_id
                intent.customer_id = parsed.customer_id or intent.customer_id
                intent.subscription_id = parsed.subscription_id or intent.subscription_id
                if parsed.event_type == "payment.succeeded":
                    intent.status = PaymentIntentStatus.SUCCEEDED
                elif parsed.event_type == "payment.failed" and intent.status == PaymentIntentStatus.PENDING:
                    intent.status = PaymentIntentStatus.FAILED
                elif parsed.event_type == "refund.succeeded":
                    intent.status = PaymentIntentStatus.REFUNDED
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
