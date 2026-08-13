"""Adaptateurs de prestataires de paiement."""

from billing.providers.manual import ManualPaymentProvider

__all__ = ["ManualPaymentProvider"]
