"""Paiement Mobile Money validé manuellement pour lancer le MVP."""
from typing import Mapping

from billing.models import CheckoutRequest, CheckoutSession, ProviderEvent


class ManualPaymentProvider:
    name = "manual"

    def __init__(self, instructions: str) -> None:
        if not instructions.strip():
            raise ValueError("Les instructions de paiement manuel sont obligatoires.")
        self.instructions = instructions.strip()

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        message = (
            f"{self.instructions}\n"
            f"Montant : {request.plan.price_minor} {request.plan.currency}.\n"
            f"Référence obligatoire : {request.payment_id}"
        )
        return CheckoutSession(
            provider=self.name,
            external_reference=request.payment_id,
            checkout_url=None,
            instructions=message,
        )

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> ProviderEvent:
        raise NotImplementedError("Le fournisseur manuel ne reçoit pas de webhooks.")
