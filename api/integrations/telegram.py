"""Jetons de liaison et persistance de l'intégration Telegram."""
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.models import TelegramConnection, TelegramConnectionStatus, WorkspaceMembership


@dataclass(frozen=True)
class PendingTelegramLink:
    user_id: uuid.UUID
    workspace_id: uuid.UUID


class TelegramLinkService:
    def __init__(self, redis: Redis, ttl_seconds: int = 600) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    def issue(self, user_id: uuid.UUID, workspace_id: uuid.UUID) -> str:
        token = secrets.token_urlsafe(24)
        payload = json.dumps(
            {"user_id": str(user_id), "workspace_id": str(workspace_id)}
        )
        self.redis.setex(self._key(token), self.ttl_seconds, payload)
        return token

    def consume(self, token: str) -> PendingTelegramLink | None:
        raw = self.redis.getdel(self._key(token))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            payload = json.loads(raw)
            return PendingTelegramLink(
                user_id=uuid.UUID(payload["user_id"]),
                workspace_id=uuid.UUID(payload["workspace_id"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _key(token: str) -> str:
        digest = hashlib.sha256(token.encode()).hexdigest()
        return f"telegram:link:{digest}"


def attach_telegram_account(
    db: Session,
    pending: PendingTelegramLink,
    telegram_user_id: int,
    telegram_chat_id: int,
) -> TelegramConnection:
    membership = db.scalar(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.workspace_id == pending.workspace_id,
            WorkspaceMembership.user_id == pending.user_id,
        )
    )
    if membership is None:
        raise ValueError("Vous n'avez plus accès à ce workspace.")

    connection = db.scalar(
        select(TelegramConnection).where(
            TelegramConnection.workspace_id == pending.workspace_id,
            TelegramConnection.user_id == pending.user_id,
        )
    )
    claimed_connection = db.scalar(
        select(TelegramConnection).where(
            TelegramConnection.telegram_user_id == telegram_user_id
        )
    )
    if claimed_connection and (
        connection is None or claimed_connection.id != connection.id
    ):
        raise ValueError("Ce compte Telegram est déjà lié à un autre workspace.")
    if connection is None:
        connection = TelegramConnection(
            workspace_id=pending.workspace_id,
            user_id=pending.user_id,
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
        )
        db.add(connection)
    else:
        connection.telegram_user_id = telegram_user_id
        connection.telegram_chat_id = telegram_chat_id
        connection.status = TelegramConnectionStatus.ACTIVE
        connection.revoked_at = None
        connection.linked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(connection)
    return connection
