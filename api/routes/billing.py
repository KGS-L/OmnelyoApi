from __future__ import annotations

import re
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from sqlalchemy.orm import Session
from sqlalchemy import select

from api.billing_providers.dodo import DodoPaymentProvider
from api.billing_providers.moneyfusion import MoneyFusionPaymentProvider
from api.billing_service import (
    BillingPGService,
    SignatureError,
    InvalidProviderPayload,
    ValidationFailure,
    CorrelationDeferred,
)
from api.config import APISettings, get_settings
from api.database import get_db
from api.dependencies import get_current_workspace_membership, require_workspace_roles
from api.models import PaymentIntent
from api.models import BillingPlan, CreditLedgerEntry, WorkspaceRole
from api.credit_service import CreditService
from api.quota_service import QuotaService

router = APIRouter(tags=["billing"])

SAFE_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


# ----- Schemas (provider-neutral, route-specific) -----

class CheckoutStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Only accept a server-known purchase code
    purchase_code: str = Field(pattern=r"^(CREATOR_MONTHLY|PRO_MONTHLY|TOPUP)$")
    customer_email: EmailStr | None = Field(default=None)
    customer_name: str | None = Field(default=None, min_length=2, max_length=120)
    customer_phone: str | None = Field(default=None, pattern=r"^\+?[0-9]{8,15}$")
    provider: str | None = Field(default=None, pattern=r"^(dodo|moneyfusion)$")


class CheckoutResponse(BaseModel):
    payment_intent_id: uuid.UUID
    checkout_url: str


class PortalResponse(BaseModel):
    url: str


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    monthly_credits: int
    social_connections_limit: int
    workspaces_limit: int
    members_per_workspace_limit: int
    concurrent_jobs_limit: int
    source_minutes_monthly_limit: int
    publications_monthly_limit: int
    storage_bytes_limit: int
    retention_days: int


class CreditSummaryResponse(BaseModel):
    workspace_id: uuid.UUID
    plan: PlanResponse
    balance: int
    period_start: str
    period_end: str


class CreditEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    entry_type: str
    amount: int
    description: str | None
    expires_at: str | None
    created_at: str


class UsageSummaryResponse(BaseModel):
    source_seconds: int
    source_seconds_limit: int
    publications: int
    publications_limit: int
    storage_bytes: int
    storage_bytes_limit: int
    retention_days: int


# ----- Helpers -----

def _ensure_billing_enabled(settings: APISettings) -> None:
    if not settings.billing_enabled:
        raise HTTPException(status_code=503, detail="La facturation est désactivée.")


def _idempotency_key(value: str | None) -> str:
    if not value:
        raise HTTPException(status_code=400, detail="En-tête X-Idempotency-Key requis.")
    if not SAFE_IDEMPOTENCY.fullmatch(value):
        raise HTTPException(status_code=400, detail="En-tête X-Idempotency-Key invalide.")
    return value


def _provider_factory(settings: APISettings, provider_name: str | None = None):
    name = provider_name or settings.billing_default_provider
    if name == "dodo":
        return DodoPaymentProvider()
    if name == "moneyfusion":
        return MoneyFusionPaymentProvider()
    raise HTTPException(status_code=503, detail="Fournisseur de paiement indisponible.")


# ----- Routes -----

@router.get("/billing/plans", response_model=list[PlanResponse])
def list_billing_plans(
    db: Annotated[Session, Depends(get_db)] = None,
) -> list[BillingPlan]:
    return list(db.scalars(select(BillingPlan).where(BillingPlan.active.is_(True)).order_by(BillingPlan.monthly_credits)))


@router.get("/workspaces/{workspace_id}/billing/credits", response_model=CreditSummaryResponse)
def credit_summary(
    workspace_id: uuid.UUID,
    membership=Depends(get_current_workspace_membership),
    db: Annotated[Session, Depends(get_db)] = None,
):
    if membership.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Workspace introuvable.")
    entitlement, plan, _, balance = CreditService().workspace_summary(db, workspace_id)
    db.commit()
    return CreditSummaryResponse(
        workspace_id=workspace_id,
        plan=PlanResponse.model_validate(plan),
        balance=balance,
        period_start=entitlement.period_start.isoformat(),
        period_end=entitlement.period_end.isoformat(),
    )


@router.get("/workspaces/{workspace_id}/billing/credits/history", response_model=list[CreditEntryResponse])
def credit_history(
    workspace_id: uuid.UUID,
    membership=Depends(get_current_workspace_membership),
    db: Annotated[Session, Depends(get_db)] = None,
    limit: int = 50,
):
    if membership.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Workspace introuvable.")
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit doit être compris entre 1 et 200.")
    _, account = CreditService().ensure_workspace(db, workspace_id)
    entries = list(db.scalars(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.account_id == account.id)
        .order_by(CreditLedgerEntry.created_at.desc(), CreditLedgerEntry.id.desc())
        .limit(limit)
    ))
    db.commit()
    return [CreditEntryResponse(
        id=e.id,
        entry_type=e.entry_type.value,
        amount=e.amount,
        description=e.description,
        expires_at=e.expires_at.isoformat() if e.expires_at else None,
        created_at=e.created_at.isoformat(),
    ) for e in entries]


@router.get("/workspaces/{workspace_id}/billing/usage", response_model=UsageSummaryResponse)
def billing_usage(
    workspace_id: uuid.UUID,
    membership=Depends(get_current_workspace_membership),
    db: Annotated[Session, Depends(get_db)] = None,
):
    if membership.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Workspace introuvable.")
    quota = QuotaService()
    plan = quota.plan_for_workspace(db, workspace_id)
    usage = quota.usage_summary(db, workspace_id)
    db.commit()
    return UsageSummaryResponse(
        **usage,
        source_seconds_limit=plan.source_minutes_monthly_limit * 60,
        publications_limit=plan.publications_monthly_limit,
        storage_bytes_limit=plan.storage_bytes_limit,
        retention_days=plan.retention_days,
    )

@router.post("/workspaces/{workspace_id}/billing/checkout", response_model=CheckoutResponse)
def start_checkout(
    workspace_id: uuid.UUID,
    payload: CheckoutStart,
    membership=Depends(get_current_workspace_membership),
    db: Annotated[Session, Depends(get_db)] = None,
    settings: Annotated[APISettings, Depends(get_settings)] = None,
    x_idempotency_key: str = Header(alias="X-Idempotency-Key"),
) -> CheckoutResponse:
    if membership.workspace_id != workspace_id:
        # Mask workspaces not belonging to the user
        raise HTTPException(status_code=404, detail="Workspace introuvable.")
    _ensure_billing_enabled(settings)
    # Never trust front-end supplied amounts/currency/product IDs/workspace IDs
    idempotency_key = _idempotency_key(x_idempotency_key)
    provider = _provider_factory(settings, payload.provider)
    service = BillingPGService(provider)
    try:
        intent: PaymentIntent = service.start_checkout(
            db,
            workspace_id=workspace_id,
            purchase_code=payload.purchase_code.strip().upper(),
            customer_email=(payload.customer_email or "").strip() or None,
            idempotency_key=idempotency_key,
            customer_name=payload.customer_name,
            customer_phone=payload.customer_phone,
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    return CheckoutResponse(payment_intent_id=intent.id, checkout_url=intent.checkout_url or "")


@router.post("/workspaces/{workspace_id}/billing/portal", response_model=PortalResponse)
def create_portal(
    workspace_id: uuid.UUID,
    membership=Depends(require_workspace_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)),
    db: Annotated[Session, Depends(get_db)] = None,
    settings: Annotated[APISettings, Depends(get_settings)] = None,
) -> PortalResponse:
    if membership.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Workspace introuvable.")
    _ensure_billing_enabled(settings)
    provider = _provider_factory(settings, "dodo")
    service = BillingPGService(provider)
    try:
        url = service.create_portal_for_workspace(db, workspace_id)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    return PortalResponse(url=url)


@router.post("/billing/webhooks/dodo")
async def dodo_webhook(
    request: Request,
    settings: Annotated[APISettings, Depends(get_settings)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    # Unauthenticated, but signature-verified
    _ensure_billing_enabled(settings)
    provider = _provider_factory(settings, "dodo")

    # Read raw body ONCE for signature verification
    body = await request.body()

    # FastAPI lower-cases headers; fetch safely
    headers = {
        "webhook-id": request.headers.get("webhook-id", ""),
        "webhook-signature": request.headers.get("webhook-signature", ""),
        "webhook-timestamp": request.headers.get("webhook-timestamp", ""),
    }
    service = BillingPGService(provider)
    try:
        result = service.process_webhook(db, headers, body)
        return {"received": True, "status": result}
    except SignatureError:
        # Invalid signature -> 401
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Signature invalide")
    except InvalidProviderPayload as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except CorrelationDeferred:
        # Valid but temporarily uncorrelated -> non-2xx to trigger retry
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Événement différé")
    except ValidationFailure as ve:
        # Strict validation failed (amount/currency/product mismatch) -> non-2xx
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(ve))
    except Exception:
        # Unexpected error but do not leak payload or secrets
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Erreur interne")


@router.post("/billing/webhooks/moneyfusion")
@router.api_route("/billing/callbacks/moneyfusion", methods=["GET", "POST"])
async def moneyfusion_notification(
    request: Request,
    settings: Annotated[APISettings, Depends(get_settings)] = None,
    db: Annotated[Session, Depends(get_db)] = None,
):
    _ensure_billing_enabled(settings)
    if request.method == "GET":
        token = request.query_params.get("token") or request.query_params.get("tokenPay")
        body = json.dumps({"token": token or ""}).encode()
    else:
        body = await request.body()
    service = BillingPGService(_provider_factory(settings, "moneyfusion"))
    try:
        result = service.process_webhook(db, {}, body)
        return {"received": True, "status": result}
    except InvalidProviderPayload as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CorrelationDeferred as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationFailure as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
