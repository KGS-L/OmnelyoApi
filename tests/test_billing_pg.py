from __future__ import annotations

import json
import uuid
from typing import Mapping

import pytest
from sqlalchemy import delete, select

from api.billing_providers.base import (
    CheckoutRequest,
    CheckoutResult,
    PaymentSnapshot,
    PortalRequest,
    PortalResult,
    ProviderPayloadError,
    ProviderSignatureError,
    SubscriptionSnapshot,
    WebhookParseResult,
)
from api.billing_service import BillingPGService, CorrelationDeferred, SignatureError, ValidationFailure
from api.database import SessionLocal
from api.models import (
    BillingInterval,
    PaymentIntent,
    PaymentIntentStatus,
    ProductType,
    Provider,
    ProviderEvent,
    ProviderEventStatus,
    ProviderPriceMapping,
    Subscription,
    SubscriptionStatus,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)


class DummyDodoProvider:
    name = "dodo"

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        return CheckoutResult(
            checkout_session_id=f"sess_{request.metadata['payment_intent_id']}",
            checkout_url="https://checkout.example.test",
        )

    def create_customer_portal(self, request: PortalRequest) -> PortalResult:
        return PortalResult(url="https://portal.example.test")

    def verify_and_parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookParseResult:
        if headers.get("webhook-signature") != "valid":
            raise ProviderSignatureError("bad signature")
        try:
            value = json.loads(body)
        except ValueError as exc:
            raise ProviderPayloadError("bad json") from exc
        data = value.get("data", {})
        return WebhookParseResult(
            provider=self.name,
            external_event_id=value["id"],
            event_type=value["type"],
            checkout_session_id=data.get("checkout_session_id"),
            payment_id=data.get("payment_id"),
            subscription_id=data.get("subscription_id"),
            product_id=data.get("product_id"),
            price_id=data.get("price_id"),
            amount_minor=data.get("amount_minor"),
            currency=data.get("currency"),
            metadata=data.get("metadata"),
            payload={"type": value["type"]},
        )

    def retrieve_payment(self, payment_id: str) -> PaymentSnapshot:
        return PaymentSnapshot(
            payment_id=payment_id,
            status="succeeded",
            amount_minor=2000,
            currency="USD",
            product_id="pdt_creator",
            price_id="price_creator",
        )

    def retrieve_subscription(self, external_subscription_id: str) -> SubscriptionSnapshot:
        return SubscriptionSnapshot(external_subscription_id=external_subscription_id, status="active")


@pytest.fixture()
def billing_db():
    session = SessionLocal()
    # This is intentionally not skipped: CI must provide migrated PostgreSQL.
    session.execute(select(1))
    workspace = Workspace(name="Billing Test", slug=f"billing-{uuid.uuid4().hex[:10]}")
    user = User(email=f"billing-{uuid.uuid4().hex[:8]}@example.test", is_active=True)
    session.add_all([workspace, user])
    session.flush()
    session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER))
    session.add(
        ProviderPriceMapping(
            provider=Provider.DODO,
            internal_plan_code="CREATOR",
            product_type=ProductType.SUBSCRIPTION,
            interval=BillingInterval.MONTH,
            external_product_id="pdt_creator",
            external_price_id="price_creator",
            expected_amount_minor=2000,
            expected_currency="USD",
            active=True,
        )
    )
    session.commit()
    yield session, workspace
    session.rollback()
    for model in (ProviderEvent, Subscription, PaymentIntent, ProviderPriceMapping, WorkspaceMembership, Workspace, User):
        session.execute(delete(model))
    session.commit()
    session.close()


def _checkout(session, workspace) -> PaymentIntent:
    return BillingPGService(DummyDodoProvider()).start_checkout(
        session, workspace.id, "CREATOR_MONTHLY", "buyer@example.test", "idem-1"
    )


def _event(intent: PaymentIntent, event_id: str = "evt_1", **overrides) -> bytes:
    data = {
        "checkout_session_id": intent.checkout_session_id,
        "payment_id": "pay_distinct_123",
        "product_id": "pdt_creator",
        "price_id": "price_creator",
        "amount_minor": 2000,
        "currency": "USD",
        "metadata": {"payment_intent_id": str(intent.id)},
    }
    data.update(overrides)
    return json.dumps({"id": event_id, "type": "payment.succeeded", "data": data}).encode()


def test_checkout_is_idempotent_and_keeps_canonical_ids_distinct(billing_db):
    session, workspace = billing_db
    first = _checkout(session, workspace)
    second = _checkout(session, workspace)
    assert first.id == second.id
    assert first.checkout_session_id.startswith("sess_")
    assert first.payment_id is None


def test_payment_webhook_is_strict_and_idempotent(billing_db):
    session, workspace = billing_db
    intent = _checkout(session, workspace)
    service = BillingPGService(DummyDodoProvider())
    headers = {"webhook-signature": "valid"}
    assert service.process_webhook(session, headers, _event(intent)) == "processed"
    session.refresh(intent)
    assert intent.status == PaymentIntentStatus.SUCCEEDED
    assert intent.payment_id == "pay_distinct_123"
    assert intent.payment_id != intent.checkout_session_id
    assert service.process_webhook(session, headers, _event(intent)) == "duplicate"

    with pytest.raises(ValidationFailure):
        service.process_webhook(session, headers, _event(intent, "evt_bad", amount_minor=1))
    failed = session.scalar(select(ProviderEvent).where(ProviderEvent.external_event_id == "evt_bad"))
    assert failed.status == ProviderEventStatus.FAILED


def test_uncorrelated_webhook_is_deferred(billing_db):
    session, _ = billing_db
    service = BillingPGService(DummyDodoProvider())
    body = json.dumps({"id": "evt_later", "type": "payment.succeeded", "data": {}}).encode()
    with pytest.raises(CorrelationDeferred):
        service.process_webhook(session, {"webhook-signature": "valid"}, body)
    event = session.scalar(select(ProviderEvent).where(ProviderEvent.external_event_id == "evt_later"))
    assert event.status == ProviderEventStatus.DEFERRED


def test_signature_failure_is_distinct_from_payload_failure(billing_db):
    session, _ = billing_db
    service = BillingPGService(DummyDodoProvider())
    with pytest.raises(SignatureError):
        service.process_webhook(session, {"webhook-signature": "bad"}, b"{}")
    with pytest.raises(ProviderPayloadError):
        DummyDodoProvider().verify_and_parse_webhook({"webhook-signature": "valid"}, b"no-json")


def test_subscription_status_comes_from_event(billing_db):
    session, workspace = billing_db
    intent = _checkout(session, workspace)
    service = BillingPGService(DummyDodoProvider())
    body = json.dumps({
        "id": "evt_cancelled",
        "type": "subscription.cancelled",
        "data": {
            "subscription_id": "sub_123",
            "checkout_session_id": intent.checkout_session_id,
            "metadata": {"payment_intent_id": str(intent.id)},
        },
    }).encode()
    service.process_webhook(session, {"webhook-signature": "valid"}, body)
    sub = session.scalar(select(Subscription).where(Subscription.external_subscription_id == "sub_123"))
    assert sub.status == SubscriptionStatus.CANCELED
