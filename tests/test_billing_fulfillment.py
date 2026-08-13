"""Tests unitaires de l'attribution des plans et crédits après paiement."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from api.billing_fulfillment import BillingFulfillmentService
from api.models import FulfillmentStatus, ProductType, Provider


class BillingFulfillmentTests(unittest.TestCase):
    def test_subscription_activates_plan_and_grants_monthly_credits(self):
        now = datetime.now(timezone.utc)
        entitlement = SimpleNamespace(
            plan_code="FREE", period_start=now, period_end=now + timedelta(days=5)
        )
        account = SimpleNamespace(id=uuid.uuid4())
        plan = SimpleNamespace(active=True, monthly_credits=30)
        intent = SimpleNamespace(
            id=uuid.uuid4(), workspace_id=uuid.uuid4(), provider=Provider.DODO,
            purchase_code="CREATOR_MONTHLY", product_type=ProductType.SUBSCRIPTION,
        )
        db = MagicMock()
        db.scalar.side_effect = [None, entitlement, account]
        db.get.return_value = plan
        with patch("api.billing_fulfillment.CreditService") as service_type:
            service_type.return_value.ensure_workspace.return_value = (entitlement, account)
            fulfillment = BillingFulfillmentService().apply_payment(db, intent, "pay_1")
        self.assertEqual(entitlement.plan_code, "CREATOR")
        self.assertEqual(fulfillment.credits_granted, 30)
        service_type.return_value.grant.assert_called_once()
        self.assertIn("pay_1", service_type.return_value.grant.call_args.args[3])

    def test_same_provider_payment_is_idempotent(self):
        existing = SimpleNamespace(id=uuid.uuid4())
        db = MagicMock()
        db.scalar.return_value = existing
        intent = SimpleNamespace(provider=Provider.DODO)
        result = BillingFulfillmentService().apply_payment(db, intent, "pay_same")
        self.assertIs(result, existing)
        db.add.assert_not_called()

    def test_refund_marks_fulfillment_without_deleting_ledger(self):
        fulfillment = SimpleNamespace(status=FulfillmentStatus.APPLIED, refunded_at=None)
        db = MagicMock()
        db.scalar.return_value = fulfillment
        intent = SimpleNamespace(provider=Provider.DODO)
        BillingFulfillmentService().record_refund(db, intent, "pay_1")
        self.assertEqual(fulfillment.status, FulfillmentStatus.REFUNDED)
        self.assertIsNotNone(fulfillment.refunded_at)

    def test_expired_subscription_returns_workspace_to_free(self):
        now = datetime.now(timezone.utc)
        entitlement = SimpleNamespace(
            plan_code="CREATOR", period_start=now, period_end=now
        )
        account = SimpleNamespace(id=uuid.uuid4())
        free = SimpleNamespace(active=True, monthly_credits=3)
        db = MagicMock()
        db.scalar.return_value = entitlement
        db.get.return_value = free
        with patch("api.billing_fulfillment.CreditService") as service_type:
            service_type.return_value.ensure_workspace.return_value = (entitlement, account)
            BillingFulfillmentService().expire_subscription(
                db, uuid.uuid4(), "sub_expired"
            )
        self.assertEqual(entitlement.plan_code, "FREE")
        self.assertEqual(service_type.return_value.grant.call_args.args[2], 3)
        self.assertIn("sub_expired", service_type.return_value.grant.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
