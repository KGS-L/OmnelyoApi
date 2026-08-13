"""Dépendances FastAPI d'authentification."""
import uuid
from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth.tokens import TokenService
from api.config import APISettings, get_settings
from api.database import get_db
from api.models import User, WorkspaceMembership, WorkspaceRole

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


def get_current_workspace_membership(
    workspace_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceMembership:
    """Résout le workspace depuis l'URL et masque ceux auxquels l'utilisateur n'appartient pas."""
    membership = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Workspace introuvable.")
    return membership


def ensure_workspace_role(
    membership: WorkspaceMembership, allowed_roles: frozenset[WorkspaceRole]
) -> WorkspaceMembership:
    if membership.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Permissions insuffisantes.")
    return membership


def require_workspace_roles(
    *roles: WorkspaceRole,
) -> Callable[..., WorkspaceMembership]:
    """Construit une dépendance de route limitée aux rôles indiqués."""
    allowed_roles = frozenset(roles)
    if not allowed_roles:
        raise ValueError("Au moins un rôle workspace est requis.")

    def dependency(
        membership: Annotated[
            WorkspaceMembership, Depends(get_current_workspace_membership)
        ],
    ) -> WorkspaceMembership:
        return ensure_workspace_role(membership, allowed_roles)

    return dependency
