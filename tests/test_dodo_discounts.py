"""Contrat de transmission des remises au checkout hébergé Dodo."""
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from api.billing_providers.base import CheckoutRequest
from api.billing_providers.dodo import DodoPaymentProvider


class DodoDiscountTests(unittest.TestCase):
    def test_checkout_preapplies_server_validated_discount(self):
        provider = DodoPaymentProvider.__new__(DodoPaymentProvider)
        provider._client = SimpleNamespace(
            checkout_sessions=SimpleNamespace(create=MagicMock(return_value=SimpleNamespace(
                session_id="sess_1", checkout_url="https://checkout.test/1"
            )))
        )
        provider._return_url = "https://app.test/billing/return"
        provider.create_checkout(CheckoutRequest(
            workspace_id=uuid.uuid4(), purchase_code="CREATOR_MONTHLY",
            customer_email="client@example.com", idempotency_key="idem-1",
            external_product_id="prod_creator", expected_amount_minor=8910,
            expected_currency="XOF", discount_codes=["JONAS10"],
            metadata={"payment_intent_id": str(uuid.uuid4())},
        ))
        kwargs = provider._client.checkout_sessions.create.call_args.kwargs
        self.assertEqual(kwargs["discount_codes"], ["JONAS10"])
        self.assertNotIn("feature_flags", kwargs)


if __name__ == "__main__":
    unittest.main()
