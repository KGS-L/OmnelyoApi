"""Tests des règles de remise, sans dépendre d'un fournisseur de paiement."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from api.billing_service import BillingPGService
from api.models import PartnerCommissionStatus, PartnerStatus
from api.partner_service import PartnerService, PromoCodeError, normalize_promo_code


class PartnerServiceTests(unittest.TestCase):
    def test_confirmed_payment_creates_one_pending_commission(self):
        attribution = SimpleNamespace(
            id=uuid.uuid4(), partner_id=uuid.uuid4(), promo_code_id=uuid.uuid4(),
            converted_at=None,
        )
        partner = SimpleNamespace(id=attribution.partner_id, commission_bps=2000)
        promo = SimpleNamespace(id=attribution.promo_code_id, redemption_count=0)
        intent = SimpleNamespace(
            id=uuid.uuid4(), referral_attribution_id=attribution.id,
            expected_amount_minor=8_910, expected_currency="XOF",
        )
        db = MagicMock()
        db.scalar.return_value = None
        db.get.side_effect = [attribution, partner, promo]
        BillingPGService._apply_partner_payment(db, intent, "payment.succeeded")
        commission = db.add.call_args.args[0]
        self.assertEqual(commission.amount_minor, 1_782)
        self.assertEqual(commission.status, PartnerCommissionStatus.PENDING)
        self.assertIsNotNone(attribution.converted_at)
        self.assertEqual(promo.redemption_count, 1)

    def test_refund_cancels_existing_commission(self):
        commission = SimpleNamespace(status=PartnerCommissionStatus.PENDING)
        db = MagicMock()
        db.scalar.return_value = commission
        intent = SimpleNamespace(id=uuid.uuid4(), referral_attribution_id=uuid.uuid4())
        BillingPGService._apply_partner_payment(db, intent, "refund.succeeded")
        self.assertEqual(commission.status, PartnerCommissionStatus.CANCELED)

    def test_codes_are_normalized_but_strict(self):
        self.assertEqual(normalize_promo_code("  jonas10 "), "JONAS10")
        with self.assertRaises(PromoCodeError):
            normalize_promo_code("x")

    def test_quote_calculates_ten_percent_server_side(self):
        now = datetime.now(timezone.utc)
        partner = SimpleNamespace(id=uuid.uuid4(), status=PartnerStatus.ACTIVE)
        promo = SimpleNamespace(
            id=uuid.uuid4(), partner_id=partner.id, code="JONAS10",
            active=True, starts_at=now - timedelta(days=1), ends_at=None,
            max_redemptions=None, redemption_count=0,
            eligible_plan_codes=["CREATOR", "PRO"], discount_bps=1000,
            discount_cycles=3,
        )
        db = MagicMock()
        db.execute.return_value.one_or_none.return_value = (promo, partner)
        quote = PartnerService().quote(db, "jonas10", "CREATOR", 9_900, now=now)
        self.assertEqual(quote.discount_amount_minor, 990)
        self.assertEqual(quote.final_amount_minor, 8_910)
        self.assertEqual(quote.discount_cycles, 3)

    def test_inactive_partner_cannot_discount(self):
        now = datetime.now(timezone.utc)
        partner = SimpleNamespace(id=uuid.uuid4(), status=PartnerStatus.SUSPENDED)
        promo = SimpleNamespace(
            id=uuid.uuid4(), code="PAUSED10", active=True,
            starts_at=now - timedelta(days=1), ends_at=None,
            max_redemptions=None, redemption_count=0,
            eligible_plan_codes=["CREATOR"], discount_bps=1000, discount_cycles=3,
        )
        db = MagicMock()
        db.execute.return_value.one_or_none.return_value = (promo, partner)
        with self.assertRaisesRegex(PromoCodeError, "indisponible"):
            PartnerService().quote(db, "PAUSED10", "CREATOR", 9_900, now=now)


if __name__ == "__main__":
    unittest.main()
