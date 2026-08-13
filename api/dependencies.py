"""Dépendances FastAPI d'authentification."""
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from api.auth.tokens import TokenService
from api.config import APISettings, get_settings
from api.database import get_db
from api.models import User

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[APISettings, Depends(get_settings)],
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentification requise.")
    try:
        user_id = TokenService(settings).decode_access(credentials.credentials)
    except (ValueError, jwt.PyJWTError):
        raise HTTPException(status_code=401, detail="Token invalide ou expiré.")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Utilisateur inactif.")
    return user
