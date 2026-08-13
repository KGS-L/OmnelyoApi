from __future__ import annotations

import os
from datetime import datetime
from typing import Mapping

from dodopayments import DodoPayments  # type: ignore[import-untyped]

from api.billing_providers.base import (
    CheckoutRequest,
    CheckoutResult,
    PaymentProvider,
    PortalRequest,
    PortalResult,
    SubscriptionSnapshot,
    WebhookParseResult,
    PaymentSnapshot,
    ProviderPayloadError,
    ProviderSignatureError,
)
from api.config import get_settings


class DodoPaymentProvider(PaymentProvider):
    name = "dodo"

    def __init__(self) -> None:
        settings = get_settings()
        # IMPORTANT: never print or log secrets
        self._client = DodoPayments(
            bearer_token=settings.dodo_api_key or os.getenv("DODO_API_KEY"),
            environment=settings.dodo_sdk_environment,
            webhook_key=settings.dodo_webhook_secret or os.getenv("DODO_WEBHOOK_SECRET"),
        )
        self._return_url = settings.dodo_return_url

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        # Server-side product mapping only; never trust frontend for product/price/amount
        session = self._client.checkout_sessions.create(
            product_cart=[{"product_id": request.external_product_id, "quantity": request.quantity}],
            customer={"email": request.customer_email} if request.customer_email else None,
            return_url=self._return_url or None,
            metadata=request.metadata or None,
        )
        # SDK responses are Pydantic models per docs; use properties without logging sensitive data
        session_id = getattr(session, "session_id", None) or getattr(session, "id", None) or ""
        checkout_url = getattr(session, "checkout_url", None) or getattr(session, "url", None) or ""
        if not session_id or not checkout_url:
            raise RuntimeError("Provider did not return a valid checkout session.")
        return CheckoutResult(checkout_session_id=session_id, checkout_url=checkout_url)

    def create_customer_portal(self, request: PortalRequest) -> PortalResult:
        portal = self._client.customers.customer_portal.create(
            customer_id=request.customer_id,
            # return_url can be optionally passed if needed:
            # return_url=get_settings().dodo_return_url or None,
        )
        link = getattr(portal, "link", None) or ""
        if not link:
            raise RuntimeError("Provider did not return a portal link.")
        return PortalResult(url=link)

    def verify_and_parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookParseResult:
        # Dodo follows Standard Webhooks: headers include webhook-id, webhook-signature, webhook-timestamp
        try:
            unwrapped = self._client.webhooks.unwrap(
                body,
                headers={
                    "webhook-id": headers.get("webhook-id", "") or headers.get("Webhook-Id", "") or "",
                    "webhook-signature": headers.get("webhook-signature", "") or headers.get("Webhook-Signature", "") or "",
                    "webhook-timestamp": headers.get("webhook-timestamp", "") or headers.get("Webhook-Timestamp", "") or "",
                },
            )
        except Exception as exc:
            raise ProviderSignatureError("Signature Dodo invalide.") from exc
        if not isinstance(unwrapped, dict):
            if hasattr(unwrapped, "model_dump"):
                unwrapped = unwrapped.model_dump(mode="json")
            else:
                raise ProviderPayloadError("Événement Dodo invalide.")
        # unwrapped is the verified JSON event; do not log content
        event_type: str = unwrapped.get("type", "")
        external_event_id: str = unwrapped.get("id", "") or unwrapped.get("event_id", "")
        provider_created_at = None
        try:
            ts = unwrapped.get("timestamp")
            if isinstance(ts, str):
                provider_created_at = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            provider_created_at = None

        data = unwrapped.get("data", {}) or {}
        # Canonical identifiers
        payment_id = data.get("payment_id")
        subscription_id = data.get("subscription_id")
        checkout_session_id = data.get("session_id") or data.get("checkout_session_id")
        customer_id = data.get("customer_id")
        # Product/price and money
        product_id = data.get("product_id")
        price_id = data.get("price_id")
        amount_minor = data.get("amount_minor") if data.get("amount_minor") is not None else data.get("amount")
        currency = (data.get("currency") or "").upper() if data.get("currency") else None
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else None

        if not external_event_id or not event_type:
            raise ProviderPayloadError("Événement Dodo incomplet.")

        # Store minimal payload for reconciliation (avoid PII)
        minimal_payload = {
            "type": event_type,
            "timestamp": unwrapped.get("timestamp"),
            "data": {
                k: data.get(k)
                for k in (
                    "payment_id",
                    "session_id",
                    "subscription_id",
                    "customer_id",
                    "product_id",
                    "price_id",
                    "amount_minor",
                    "currency",
                    "status",
                    "metadata",
                )
                if k in data
            },
        }

        return WebhookParseResult(
            provider=self.name,
            external_event_id=external_event_id,
            event_type=event_type,
            provider_created_at=provider_created_at,
            checkout_session_id=checkout_session_id,
            payment_id=payment_id,
            subscription_id=subscription_id,
            customer_id=customer_id,
            product_id=product_id,
            price_id=price_id,
            amount_minor=int(amount_minor) if isinstance(amount_minor, int) else None,
            currency=currency,
            metadata=metadata,
            payload=minimal_payload,
        )

    def retrieve_payment(self, payment_id: str) -> PaymentSnapshot:
        payment = self._client.payments.retrieve(payment_id)
        status = getattr(payment, "status", None) or getattr(payment, "payment_status", None) or ""
        amount_minor = getattr(payment, "amount_minor", None)
        if amount_minor is None:
            amount_minor = getattr(payment, "amount", None)
        currency = getattr(payment, "currency", None) or None
        product_id = getattr(payment, "product_id", None) or None
        price_id = getattr(payment, "price_id", None) or None
        metadata = getattr(payment, "metadata", None) if hasattr(payment, "metadata") else None
        return PaymentSnapshot(
            payment_id=payment_id,
            status=str(status),
            amount_minor=int(amount_minor) if isinstance(amount_minor, int) else None,
            currency=str(currency).upper() if isinstance(currency, str) else None,
            product_id=product_id,
            price_id=price_id,
            metadata=metadata if isinstance(metadata, dict) else None,
        )

    def retrieve_subscription(self, external_subscription_id: str) -> SubscriptionSnapshot:
        sub = self._client.subscriptions.retrieve(external_subscription_id)
        status = getattr(sub, "status", None) or ""
        current_period_end = getattr(sub, "current_period_end", None)
        customer_id = getattr(sub, "customer_id", None)
        return SubscriptionSnapshot(
            external_subscription_id=external_subscription_id,
            status=str(status),
            current_period_end=current_period_end,
            customer_id=customer_id,
        )
