"""Access JWT courts et refresh tokens rotatifs stockés hachés."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import APISettings
from api.models import RefreshSession, User


class TokenService:
    def __init__(self, settings: APISettings) -> None:
        self.settings = settings

    def issue_pair(self, db: Session, user: User) -> tuple[str, str]:
        now = datetime.now(timezone.utc)
        access = jwt.encode(
            {
                "sub": str(user.id), "type": "access", "iat": now,
                "exp": now + timedelta(minutes=self.settings.api_access_token_minutes),
                "jti": str(uuid.uuid4()),
            },
            self.settings.api_jwt_secret,
            algorithm=self.settings.api_jwt_algorithm,
        )
        refresh = secrets.token_urlsafe(48)
        db.add(
            RefreshSession(
                user_id=user.id,
                token_hash=self._hash(refresh),
                expires_at=now + timedelta(days=self.settings.api_refresh_token_days),
            )
        )
        db.commit()
        return access, refresh

    def rotate(self, db: Session, refresh_token: str) -> tuple[str, str]:
        now = datetime.now(timezone.utc)
        session = db.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == self._hash(refresh_token))
        )
        if not session or session.revoked_at or session.expires_at <= now:
            raise ValueError("Refresh token invalide ou expiré.")
        user = db.get(User, session.user_id)
        if not user or not user.is_active:
            raise ValueError("Utilisateur inactif.")
        session.revoked_at = now
        db.commit()
        return self.issue_pair(db, user)

    def revoke(self, db: Session, refresh_token: str) -> bool:
        session = db.scalar(
            select(RefreshSession).where(RefreshSession.token_hash == self._hash(refresh_token))
        )
        if not session or session.revoked_at:
            return False
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
        return True

    def decode_access(self, token: str) -> uuid.UUID:
        payload = jwt.decode(
            token,
            self.settings.api_jwt_secret,
            algorithms=[self.settings.api_jwt_algorithm],
        )
        if payload.get("type") != "access":
            raise ValueError("Type de token invalide.")
        return uuid.UUID(payload["sub"])

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
