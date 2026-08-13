from __future__ import annotations

import re
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from sqlalchemy.orm import Session

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
from api.models import WorkspaceRole

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
