"""Objets métier communs à Dodo, PayDunya, Paddle et au paiement manuel."""
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProductType(StrEnum):
    CREDITS = "credits"
    SUBSCRIPTION = "subscription"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    product_type: ProductType
    price_minor: int
    currency: str
    credits: int = 0
    interval: str | None = None
    active: bool = True


@dataclass(frozen=True)
class CheckoutRequest:
    payment_id: str
    workspace_id: str
    customer_email: str
    plan: Plan
    success_url: str | None = None
    cancel_url: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckoutSession:
    provider: str
    external_reference: str
    checkout_url: str | None
    instructions: str | None = None


@dataclass(frozen=True)
class ProviderEvent:
    provider: str
    event_id: str
    event_type: str
    external_reference: str
    amount_minor: int | None = None
    currency: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
