"""Endpoints passwordless email, Google et sessions."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis import Redis
from sqlalchemy.orm import Session

from api.auth.accounts import get_or_create_user
from api.auth.google import verify_google_credential
from api.auth.otp import EmailSender, OTPService
from api.auth.tokens import TokenService
from api.config import APISettings, get_settings
from api.database import get_db
from api.models import IdentityProvider
from api.schemas import GoogleLogin, LogoutRequest, OTPRequest, OTPVerify, RefreshRequest, TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(db: Session, settings: APISettings, user) -> TokenPair:
    access, refresh = TokenService(settings).issue_pair(db, user)
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/email/request-otp", status_code=status.HTTP_202_ACCEPTED)
def request_otp(payload: OTPRequest, settings: Annotated[APISettings, Depends(get_settings)]):
    redis = Redis.from_url(settings.redis_url)
    try:
        code = OTPService(redis, settings).issue(str(payload.email))
        EmailSender().send_otp(str(payload.email), code)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    response = {"message": "Si l'adresse est valide, un code a été envoyé."}
    if settings.api_environment != "production" and settings.expose_dev_otp:
        response["dev_code"] = code
    return response


@router.post("/email/verify", response_model=TokenPair)
def verify_otp(
    payload: OTPVerify,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[APISettings, Depends(get_settings)],
):
    redis = Redis.from_url(settings.redis_url)
    try:
        valid = OTPService(redis, settings).verify(str(payload.email), payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    if not valid:
        raise HTTPException(status_code=401, detail="Code invalide ou expiré.")
    email = str(payload.email).lower()
    user = get_or_create_user(
        db, IdentityProvider.EMAIL, email, email, email_verified=True
    )
    return _tokens(db, settings, user)


@router.post("/google", response_model=TokenPair)
def google_login(
    payload: GoogleLogin,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[APISettings, Depends(get_settings)],
):
    try:
        claims = verify_google_credential(payload.credential, settings.google_web_client_id)
        user = get_or_create_user(
            db,
            IdentityProvider.GOOGLE,
            claims["sub"],
            claims["email"],
            email_verified=bool(claims.get("email_verified")),
            display_name=claims.get("name"),
            avatar_url=claims.get("picture"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return _tokens(db, settings, user)


@router.post("/refresh", response_model=TokenPair)
def refresh(
    payload: RefreshRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[APISettings, Depends(get_settings)],
):
    try:
        access, refresh_token = TokenService(settings).rotate(db, payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    return TokenPair(access_token=access, refresh_token=refresh_token)


@router.post("/logout", status_code=204)
def logout(
    payload: LogoutRequest,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[APISettings, Depends(get_settings)],
):
    TokenService(settings).revoke(db, payload.refresh_token)
