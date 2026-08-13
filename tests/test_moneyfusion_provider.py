from __future__ import annotations

import json
import uuid

import pytest

from api.billing_providers.base import CheckoutRequest, ProviderPayloadError
from api.billing_providers.moneyfusion import MoneyFusionPaymentProvider


class FakeMoneyFusionClient:
    def __init__(self) -> None:
        self.created = None
        self.status = "paid"

    def create_payment(self, **kwargs):
        self.created = kwargs
        return {"statut": True, "token": "token_123", "url": "https://pay.example/token_123"}

    def get_payment(self, token):
        return {
            "statut": True,
            "data": {
                "_id": "transaction_123",
                "tokenPay": token,
                "Montant": 5000,
                "statut": self.status,
                "personal_Info": [{"orderId": 42}],
                "createdAt": "2026-08-13T08:00:00Z",
            },
        }


def _provider():
    client = FakeMoneyFusionClient()
    provider = MoneyFusionPaymentProvider(client=client)
    provider._return_url = "https://api.example/callback"
    provider._webhook_url = "https://api.example/webhook"
    return provider, client


def test_moneyfusion_checkout_uses_server_amount_and_callback_urls():
    provider, client = _provider()
    result = provider.create_checkout(
        CheckoutRequest(
            workspace_id=uuid.uuid4(),
            purchase_code="TOPUP",
            customer_name="Jonas",
            customer_phone="22670000000",
            external_product_id="topup",
            expected_amount_minor=5000,
            expected_currency="XOF",
            metadata={"payment_intent_id": str(uuid.uuid4())},
        )
    )
    assert result.checkout_session_id == "token_123"
    assert client.created["total_price"] == "5000"
    assert client.created["webhook_url"] == "https://api.example/webhook"
    assert isinstance(client.created["order_id"], int)


def test_moneyfusion_webhook_is_confirmed_server_side():
    provider, client = _provider()
    parsed = provider.verify_and_parse_webhook({}, json.dumps({"tokenPay": "token_123", "event": "forged"}).encode())
    assert parsed.event_type == "payment.succeeded"
    assert parsed.amount_minor == 5000
    assert parsed.payment_id == "transaction_123"
    client.status = "pending"
    parsed = provider.verify_and_parse_webhook({}, b'{"token":"token_123"}')
    assert parsed.event_type == "payment.pending"


def test_moneyfusion_rejects_missing_or_mismatched_token():
    provider, client = _provider()
    with pytest.raises(ProviderPayloadError):
        provider.verify_and_parse_webhook({}, b"{}")
    original = client.get_payment
    client.get_payment = lambda token: {"statut": True, "data": {"tokenPay": "other"}}
    with pytest.raises(ProviderPayloadError):
        provider.verify_and_parse_webhook({}, b'{"token":"token_123"}')
    client.get_payment = original
