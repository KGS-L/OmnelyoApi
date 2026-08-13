"""Orchestrateur de facturation utilisé par l'API, sans dépendre d'un prestataire."""
from typing import Mapping

from billing.models import CheckoutRequest, CheckoutSession
from billing.providers.base import PaymentProvider
from billing.repository import BillingRepository


class BillingService:
    def __init__(
        self,
        repository: BillingRepository,
        providers: list[PaymentProvider],
    ) -> None:
        self.repository = repository
        self.providers = {provider.name: provider for provider in providers}
        if not self.providers:
            raise ValueError("Au moins un fournisseur de paiement est requis.")

    def start_checkout(
        self,
        workspace_id: str,
        plan_code: str,
        customer_email: str,
        provider_name: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
    ) -> CheckoutSession:
        provider = self.providers.get(provider_name)
        if not provider:
            raise ValueError(f"Fournisseur de paiement indisponible : {provider_name}")
        plan = self.repository.get_plan(plan_code)
        if not plan:
            raise ValueError(f"Plan inconnu ou inactif : {plan_code}")
        payment_id = self.repository.create_payment(
            workspace_id, plan, provider.name, customer_email
        )
        session = provider.create_checkout(
            CheckoutRequest(
                payment_id=payment_id,
                workspace_id=workspace_id,
                customer_email=customer_email,
                plan=plan,
                success_url=success_url,
                cancel_url=cancel_url,
            )
        )
        self.repository.set_external_reference(payment_id, session.external_reference)
        return session

    def confirm_manual_payment(self, payment_id: str, transaction_reference: str) -> bool:
        if "manual" not in self.providers:
            raise ValueError("Le paiement manuel n'est pas activé.")
        if not transaction_reference.strip():
            raise ValueError("La référence de transaction est obligatoire.")
        return self.repository.settle_payment(
            payment_id,
            transaction_reference.strip(),
            expected_provider="manual",
        )

    def handle_webhook(
        self, provider_name: str, headers: Mapping[str, str], body: bytes
    ) -> bool:
        provider = self.providers.get(provider_name)
        if not provider:
            raise ValueError(f"Fournisseur de paiement indisponible : {provider_name}")
        event = provider.parse_webhook(headers, body)
        return self.repository.apply_provider_event(event)
