"""État OAuth à usage unique et persistance des connexions sociales."""
import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.integrations.social import OAuthGrant
from api.models import (
    Channel,
    ChannelPlatform,
    ChannelStatus,
    SocialConnection,
    SocialConnectionStatus,
    WorkspaceMembership,
)
from api.security.social_credentials import SocialCredentialCipher


@dataclass(frozen=True)
class PendingSocialOAuth:
    user_id: uuid.UUID
    workspace_id: uuid.UUID
    platform: ChannelPlatform


class SocialOAuthStateService:
    def __init__(self, redis: Redis, ttl_seconds: int = 600) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    def issue(
        self, user_id: uuid.UUID, workspace_id: uuid.UUID, platform: ChannelPlatform
    ) -> str:
        state = secrets.token_urlsafe(32)
        payload = json.dumps(
            {
                "user_id": str(user_id),
                "workspace_id": str(workspace_id),
                "platform": platform.value,
            }
        )
        self.redis.setex(self._key(state), self.ttl_seconds, payload)
        return state

    def consume(self, state: str) -> PendingSocialOAuth | None:
        raw = self.redis.getdel(self._key(state))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        try:
            payload = json.loads(raw)
            return PendingSocialOAuth(
                user_id=uuid.UUID(payload["user_id"]),
                workspace_id=uuid.UUID(payload["workspace_id"]),
                platform=ChannelPlatform(payload["platform"]),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _key(state: str) -> str:
        return f"social:oauth:{hashlib.sha256(state.encode()).hexdigest()}"


def persist_oauth_grant(
    db: Session,
    pending: PendingSocialOAuth,
    grant: OAuthGrant,
    cipher: SocialCredentialCipher,
    *,
    commit: bool = True,
) -> tuple[SocialConnection, list[Channel]]:
    membership = db.scalar(
        select(WorkspaceMembership.id).where(
            WorkspaceMembership.workspace_id == pending.workspace_id,
            WorkspaceMembership.user_id == pending.user_id,
        )
    )
    if membership is None:
        raise ValueError("Vous n'avez plus accès à ce workspace.")
    connection = db.scalar(
        select(SocialConnection).where(
            SocialConnection.workspace_id == pending.workspace_id,
            SocialConnection.platform == pending.platform,
            SocialConnection.provider_account_id == grant.provider_account_id,
        )
    )
    values = {
        "access_token_encrypted": cipher.encrypt(grant.access_token),
        "refresh_token_encrypted": (
            cipher.encrypt(grant.refresh_token) if grant.refresh_token else None
        ),
        "scopes": sorted(set(grant.scopes)),
        "expires_at": grant.expires_at,
        "status": SocialConnectionStatus.ACTIVE,
        "provider_metadata": grant.provider_metadata,
        "last_verified_at": datetime.now(timezone.utc),
        "revoked_at": None,
    }
    if connection is None:
        connection = SocialConnection(
            workspace_id=pending.workspace_id,
            platform=pending.platform,
            provider_account_id=grant.provider_account_id,
            **values,
        )
        db.add(connection)
        db.flush()
    else:
        for field, value in values.items():
            setattr(connection, field, value)
    channels: list[Channel] = []
    for remote in grant.channels:
        channel = db.scalar(
            select(Channel).where(
                Channel.platform == pending.platform,
                Channel.external_id == remote.external_id,
            )
        )
        if channel is not None and channel.workspace_id != pending.workspace_id:
            raise ValueError("Cette destination sociale appartient déjà à un autre workspace.")
        if channel is None:
            channel = Channel(
                workspace_id=pending.workspace_id,
                connection_id=connection.id,
                platform=pending.platform,
                external_id=remote.external_id,
                name=remote.name,
                handle=remote.handle,
                avatar_url=remote.avatar_url,
            )
            db.add(channel)
        else:
            channel.connection_id = connection.id
            channel.name = remote.name
            channel.handle = remote.handle
            channel.avatar_url = remote.avatar_url
            channel.status = ChannelStatus.ACTIVE
        channels.append(channel)
    if commit:
        db.commit()
        db.refresh(connection)
        for channel in channels:
            db.refresh(channel)
    else:
        db.flush()
    return connection, channels


def persist_oauth_grants(
    db: Session,
    pending: PendingSocialOAuth,
    grants: list[OAuthGrant],
    cipher: SocialCredentialCipher,
) -> tuple[list[SocialConnection], list[Channel]]:
    if not grants:
        raise ValueError("Le fournisseur n'a retourné aucun compte accessible.")
    provider_ids = [grant.provider_account_id for grant in grants]
    if len(provider_ids) != len(set(provider_ids)):
        raise ValueError("Le fournisseur a retourné des comptes dupliqués.")
    connections: list[SocialConnection] = []
    channels: list[Channel] = []
    for grant in grants:
        connection, grant_channels = persist_oauth_grant(
            db, pending, grant, cipher, commit=False
        )
        connections.append(connection)
        channels.extend(grant_channels)
    db.commit()
    for connection in connections:
        db.refresh(connection)
    for channel in channels:
        db.refresh(channel)
    return connections, channels
