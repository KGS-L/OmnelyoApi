"""Création et rapprochement sécurisé des identités utilisateur."""
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import (
    AuthIdentity, IdentityProvider, User, Workspace, WorkspaceMembership, WorkspaceRole,
)


def get_or_create_user(
    db: Session,
    provider: IdentityProvider,
    subject: str,
    email: str,
    email_verified: bool,
    display_name: str | None = None,
    avatar_url: str | None = None,
) -> User:
    identity = db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == provider, AuthIdentity.provider_subject == subject
        )
    )
    if identity:
        return db.get(User, identity.user_id)

    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user and provider != IdentityProvider.EMAIL:
        raise ValueError(
            "Un compte existe déjà avec cette adresse. Connecte-toi par email, "
            "puis lie Google depuis les paramètres du compte."
        )
    if user and not email_verified:
        raise ValueError("Cette adresse doit être vérifiée avant de lier une identité.")
    if not user:
        user = User(
            email=normalized_email,
            email_verified=email_verified,
            display_name=display_name,
            avatar_url=avatar_url,
        )
        db.add(user)
        db.flush()
        slug = _workspace_slug(display_name or normalized_email.split("@")[0], user.id)
        workspace = Workspace(name=f"Espace de {display_name or normalized_email}", slug=slug)
        db.add(workspace)
        db.flush()
        db.add(
            WorkspaceMembership(
                workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER
            )
        )
    else:
        user.email_verified = user.email_verified or email_verified
        user.display_name = user.display_name or display_name
        user.avatar_url = user.avatar_url or avatar_url
    db.add(AuthIdentity(user_id=user.id, provider=provider, provider_subject=subject))
    db.commit()
    db.refresh(user)
    return user


def _workspace_slug(value: str, user_id: uuid.UUID) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:50] or "workspace"
    return f"{base}-{str(user_id)[:8]}"
