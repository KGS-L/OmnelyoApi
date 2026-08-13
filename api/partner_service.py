"""Règles commerciales du programme partenaire, indépendantes des providers."""
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import PartnerProfile, PartnerStatus, PromoCode, ReferralAttribution

PROMO_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,31}$")


@dataclass(frozen=True)
class PromoQuote:
    promo_code_id: uuid.UUID
    partner_id: uuid.UUID
    code: str
    original_amount_minor: int
    discount_amount_minor: int
    final_amount_minor: int
    discount_bps: int
    discount_cycles: int


class PromoCodeError(ValueError):
    pass


def normalize_promo_code(value: str) -> str:
    code = value.strip().upper()
    if not PROMO_CODE_PATTERN.fullmatch(code):
        raise PromoCodeError("Code promotionnel invalide.")
    return code


class PartnerService:
    def quote(
        self,
        db: Session,
        code: str,
        plan_code: str,
        amount_minor: int,
        *,
        now: datetime | None = None,
    ) -> PromoQuote:
        if amount_minor <= 0:
            raise ValueError("Le montant tarifaire doit être positif.")
        current = now or datetime.now(timezone.utc)
        normalized = normalize_promo_code(code)
        row = db.execute(
            select(PromoCode, PartnerProfile)
            .join(PartnerProfile, PartnerProfile.id == PromoCode.partner_id)
            .where(PromoCode.code == normalized)
        ).one_or_none()
        if row is None:
            raise PromoCodeError("Code promotionnel inconnu.")
        promo, partner = row
        if not promo.active or partner.status is not PartnerStatus.ACTIVE:
            raise PromoCodeError("Code promotionnel indisponible.")
        starts_at = _aware(promo.starts_at)
        ends_at = _aware(promo.ends_at) if promo.ends_at else None
        if current < starts_at or ends_at is not None and current >= ends_at:
            raise PromoCodeError("Code promotionnel expiré ou pas encore actif.")
        if promo.max_redemptions is not None and promo.redemption_count >= promo.max_redemptions:
            raise PromoCodeError("Ce code promotionnel a atteint sa limite.")
        if plan_code.strip().upper() not in set(promo.eligible_plan_codes or []):
            raise PromoCodeError("Ce code n'est pas valable pour cette offre.")
        discount = amount_minor * promo.discount_bps // 10_000
        return PromoQuote(
            promo_code_id=promo.id,
            partner_id=partner.id,
            code=promo.code,
            original_amount_minor=amount_minor,
            discount_amount_minor=discount,
            final_amount_minor=amount_minor - discount,
            discount_bps=promo.discount_bps,
            discount_cycles=promo.discount_cycles,
        )

    def attribute(
        self,
        db: Session,
        workspace_id: uuid.UUID,
        quote: PromoQuote,
        *,
        now: datetime | None = None,
    ) -> ReferralAttribution:
        existing = db.scalar(select(ReferralAttribution).where(
            ReferralAttribution.workspace_id == workspace_id
        ))
        if existing is not None:
            if existing.promo_code_id != quote.promo_code_id:
                raise PromoCodeError("Ce workspace est déjà attribué à un partenaire.")
            return existing
        current = now or datetime.now(timezone.utc)
        attribution = ReferralAttribution(
            partner_id=quote.partner_id,
            promo_code_id=quote.promo_code_id,
            workspace_id=workspace_id,
            expires_at=current + timedelta(days=30),
        )
        db.add(attribution)
        db.flush()
        return attribution


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
