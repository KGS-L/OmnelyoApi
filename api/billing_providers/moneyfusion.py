from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Mapping

from api.billing_providers.base import (
    CheckoutRequest,
    CheckoutResult,
    PaymentProvider,
    PaymentSnapshot,
    PortalRequest,
    PortalResult,
    ProviderPayloadError,
    SubscriptionSnapshot,
    WebhookParseResult,
)
from api.config import get_settings


class MoneyFusionPaymentProvider(PaymentProvider):
    """MoneyFusion adapter.

    MoneyFusion does not document signed webhooks. Incoming notifications are
    therefore treated only as hints and are always confirmed with get_payment.
    """

    name = "moneyfusion"

    def __init__(self, client: Any | None = None) -> None:
        settings = get_settings()
        if client is None:
            try:
                from apiMoneyFusion import PaymentClient  # type: ignore[import-untyped]
            except ImportError as exc:  # pragma: no cover - deployment guard
                raise RuntimeError("apiMoneyFusion n'est pas installé.") from exc
            if not settings.moneyfusion_api_key_url:
                raise RuntimeError("MONEYFUSION_API_KEY_URL n'est pas configurée.")
            client = PaymentClient(api_key_url=settings.moneyfusion_api_key_url)
        self._client = client
        self._return_url = settings.moneyfusion_return_url
        self._webhook_url = settings.moneyfusion_webhook_url

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        if not request.customer_phone or not request.customer_name:
            raise ValueError("MoneyFusion exige le nom et le téléphone du client.")
        if not self._webhook_url:
            raise RuntimeError("MONEYFUSION_WEBHOOK_URL n'est pas configurée.")
        local_intent_id = uuid.UUID((request.metadata or {})["payment_intent_id"])
        kwargs: dict[str, Any] = {
            "total_price": str(request.expected_amount_minor),
            "articles": [{"name": request.purchase_code, "price": str(request.expected_amount_minor), "quantity": request.quantity}],
            "numero_send": request.customer_phone,
            "nom_client": request.customer_name,
            "user_id": request.workspace_id.int % 2_147_483_647,
            "order_id": local_intent_id.int % 2_147_483_647,
            "return_url": self._return_url,
            "webhook_url": self._webhook_url,
        }
        result = self._client.create_payment(**kwargs)
        if not isinstance(result, dict) or result.get("statut") is not True:
            raise RuntimeError("MoneyFusion a refusé la création du paiement.")
        token, url = result.get("token"), result.get("url")
        if not isinstance(token, str) or not token or not isinstance(url, str) or not url:
            raise RuntimeError("Réponse de création MoneyFusion invalide.")
        return CheckoutResult(checkout_session_id=token, checkout_url=url)

    def create_customer_portal(self, request: PortalRequest) -> PortalResult:
        raise ValueError("MoneyFusion ne fournit pas de portail client documenté.")

    def _confirmed_data(self, token: str) -> dict[str, Any]:
        result = self._client.get_payment(token)
        if not isinstance(result, dict) or result.get("statut") is not True or not isinstance(result.get("data"), dict):
            raise ProviderPayloadError("Paiement MoneyFusion introuvable ou réponse invalide.")
        data = result["data"]
        if data.get("tokenPay") != token:
            raise ProviderPayloadError("Le jeton MoneyFusion confirmé ne correspond pas.")
        return data

    @staticmethod
    def _metadata(data: dict[str, Any]) -> dict[str, str] | None:
        personal = data.get("personal_Info")
        if not isinstance(personal, list):
            return None
        for item in personal:
            if isinstance(item, dict) and item.get("orderId"):
                return {"payment_intent_id": str(item["orderId"])}
        return None

    def verify_and_parse_webhook(self, headers: Mapping[str, str], body: bytes) -> WebhookParseResult:
        try:
            payload = json.loads(body)
        except (TypeError, ValueError) as exc:
            raise ProviderPayloadError("Payload MoneyFusion invalide.") from exc
        if not isinstance(payload, dict):
            raise ProviderPayloadError("Payload MoneyFusion invalide.")
        token = payload.get("tokenPay") or payload.get("token")
        if not isinstance(token, str) or not token:
            raise ProviderPayloadError("Jeton MoneyFusion manquant.")
        data = self._confirmed_data(token)
        status = str(data.get("statut", "")).strip().lower()
        event_type = {
            "paid": "payment.succeeded",
            "failure": "payment.failed",
            "no paid": "payment.failed",
            "pending": "payment.pending",
        }.get(status)
        if event_type is None:
            raise ProviderPayloadError("Statut MoneyFusion inconnu.")
        created_at = None
        if isinstance(data.get("createdAt"), str):
            try:
                created_at = datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
            except ValueError:
                pass
        amount = data.get("Montant")
        transaction_id = data.get("_id") or data.get("numeroTransaction") or token
        return WebhookParseResult(
            provider=self.name,
            external_event_id=f"{token}:{status}",
            event_type=event_type,
            provider_created_at=created_at,
            checkout_session_id=token,
            payment_id=str(transaction_id),
            amount_minor=int(amount) if isinstance(amount, (int, float)) else None,
            currency="XOF",
            metadata=self._metadata(data),
            payload={"tokenPay": token, "statut": status, "createdAt": data.get("createdAt")},
        )

    def retrieve_payment(self, payment_id: str) -> PaymentSnapshot:
        data = self._confirmed_data(payment_id)
        amount = data.get("Montant")
        return PaymentSnapshot(
            payment_id=str(data.get("_id") or data.get("numeroTransaction") or payment_id),
            status=str(data.get("statut", "")),
            amount_minor=int(amount) if isinstance(amount, (int, float)) else None,
            currency="XOF",
            metadata=self._metadata(data),
        )

    def retrieve_subscription(self, external_subscription_id: str) -> SubscriptionSnapshot:
        raise ValueError("MoneyFusion ne fournit pas d'abonnements récurrents documentés.")
