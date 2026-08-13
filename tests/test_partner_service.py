"""Tests des règles de remise, sans dépendre d'un fournisseur de paiement."""
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from api.models import PartnerStatus
from api.partner_service import PartnerService, PromoCodeError, normalize_promo_code


class PartnerServiceTests(unittest.TestCase):
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
