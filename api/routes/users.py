"""Profil du compte connecté."""
from typing import Annotated

from fastapi import APIRouter, Depends

from api.dependencies import get_current_user
from api.models import User
from api.schemas import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(get_current_user)]):
    return user
