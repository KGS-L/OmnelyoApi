from __future__ import annotations

import uuid
from datetime import datetime
from typing import Mapping, Protocol

from pydantic import BaseModel, Field


# Provider-neutral requests/responses used by services and routes

class CheckoutRequest(BaseModel):
    workspace_id: uuid.UUID
    purchase_code: str  # e.g., CREATOR_MONTHLY | PRO_MONTHLY | TOPUP
    customer_email: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    idempotency_key: str | None = None
    # Resolved server-side from ProviderPriceMapping for the selected provider
    external_product_id: str
    expected_amount_minor: int
    expected_currency: str
    quantity: int = 1
    discount_codes: list[str] = Field(default_factory=list)
    # Optional metadata forwarded to provider (e.g., local payment_intent_id)
    metadata: dict[str, str] | None = None


class CheckoutResult(BaseModel):
    # Canonical checkout session identifier
    checkout_session_id: str
    checkout_url: str


class PortalRequest(BaseModel):
    # Customer portal requires a provider-side customer id
    customer_id: str


class PortalResult(BaseModel):
    url: str


class WebhookParseResult(BaseModel):
    provider: str
    external_event_id: str
    event_type: str
    provider_created_at: datetime | None = None
    # Canonical identifiers surfaced distinctly (never collapse them)
    checkout_session_id: str | None = None
    payment_id: str | None = None
    subscription_id: str | None = None
    customer_id: str | None = None
    # Product/price correlation
    product_id: str | None = None
    price_id: str | None = None
    # Monetary data (minor units & 3-letter ISO currency)
    amount_minor: int | None = None
    currency: str | None = None
    # Signed-back metadata (e.g., local payment_intent_id)
    metadata: dict[str, str] | None = None
    # Minimal payload for reconciliation (no PII/secrets)
    payload: dict


class PaymentSnapshot(BaseModel):
    # Canonical payment id
    payment_id: str
    status: str
    amount_minor: int | None = None
    currency: str | None = None
    product_id: str | None = None
    price_id: str | None = None
    metadata: dict[str, str] | None = None


class SubscriptionSnapshot(BaseModel):
    external_subscription_id: str
    status: str
    current_period_end: datetime | None = None
    customer_id: str | None = None


class PaymentProvider(Protocol):
    name: str

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        """Create a provider checkout/session for a resolved product mapping."""

    def create_customer_portal(self, request: PortalRequest) -> PortalResult:
        """Create a short-lived customer portal session."""

    def verify_and_parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookParseResult:
        """Verify provider signature using raw body + headers, then return a normalized event."""

    def retrieve_payment(self, payment_id: str) -> PaymentSnapshot:
        """Retrieve a payment by provider payment id."""

    def retrieve_subscription(self, external_subscription_id: str) -> SubscriptionSnapshot:
        """Retrieve a subscription by provider reference."""


class ProviderSignatureError(ValueError):
    """The provider rejected the webhook authentication/signature."""


class ProviderPayloadError(ValueError):
    """The provider payload is authenticated but malformed."""
