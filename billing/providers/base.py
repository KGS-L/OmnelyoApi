"""Contrat que doit respecter chaque passerelle de paiement."""
from typing import Mapping, Protocol

from billing.models import CheckoutRequest, CheckoutSession, ProviderEvent


class PaymentProvider(Protocol):
    name: str

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        """Crée une session ou des instructions de paiement."""

    def parse_webhook(self, headers: Mapping[str, str], body: bytes) -> ProviderEvent:
        """Vérifie la signature puis normalise un webhook."""
