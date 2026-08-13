"""Profil du compte connecté."""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies import get_current_user
from api.models import PartnerProfile, User
from api.schemas import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def me(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    partner_status = db.scalar(
        select(PartnerProfile.status).where(PartnerProfile.user_id == user.id)
    )
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        email_verified=user.email_verified,
        platform_role=user.platform_role,
        partner_status=partner_status,
    )
