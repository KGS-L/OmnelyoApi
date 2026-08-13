"""Connexion OAuth générique des plateformes sociales."""
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import APISettings, get_settings
from api.database import get_db
from api.dependencies import get_current_user, require_workspace_roles
from api.integrations.social import SocialPublisherError, social_publishers
from api.integrations.social_oauth import (
    SocialOAuthStateService,
    persist_oauth_grants,
)
from api.models import (
    Channel,
    ChannelPlatform,
    ChannelStatus,
    SocialConnection,
    SocialConnectionStatus,
    User,
    WorkspaceMembership,
    WorkspaceRole,
)
from api.schemas import (
    SocialConnectionResponse,
    SocialOAuthCallbackResponse,
    SocialOAuthStartResponse,
)
from api.security.social_credentials import SocialCredentialCipher
from api.quota_service import QuotaExceeded, QuotaService

workspace_router = APIRouter(
    prefix="/workspaces/{workspace_id}/integrations/social", tags=["integrations"]
)
callback_router = APIRouter(prefix="/integrations/social", tags=["integrations"])


def _callback_uri(settings: APISettings, platform: ChannelPlatform) -> str:
    base = settings.social_oauth_callback_base_url.rstrip("/")
    if not base:
        raise HTTPException(status_code=503, detail="Les callbacks sociaux ne sont pas configurés.")
    return f"{base}/{platform.value}/callback"


def _publisher(platform: ChannelPlatform):
    try:
        return social_publishers.get(platform)
    except SocialPublisherError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@workspace_router.post(
    "/{platform}/connect", response_model=SocialOAuthStartResponse
)
def start_social_oauth(
    workspace_id: uuid.UUID,
    platform: ChannelPlatform,
    membership: Annotated[
        WorkspaceMembership,
        Depends(require_workspace_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)),
    ],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[APISettings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
) -> SocialOAuthStartResponse:
    try:
        QuotaService().ensure_social_connection_available(db, workspace_id)
        db.commit()
    except QuotaExceeded as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    publisher = _publisher(platform)
    callback_uri = _callback_uri(settings, platform)
    state_service = SocialOAuthStateService(
        Redis.from_url(settings.redis_url), settings.social_oauth_state_ttl_seconds
    )
    state = state_service.issue(user.id, workspace_id, platform)
    try:
        url = publisher.connect(state, callback_uri)
    except SocialPublisherError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return SocialOAuthStartResponse(
        authorization_url=url,
        expires_in=settings.social_oauth_state_ttl_seconds,
    )


@callback_router.get("/{platform}/callback", response_model=SocialOAuthCallbackResponse)
def finish_social_oauth(
    platform: ChannelPlatform,
    state: Annotated[str, Query(min_length=20, max_length=512)],
    code: Annotated[str, Query(min_length=1, max_length=4096)],
    settings: Annotated[APISettings, Depends(get_settings)],
    db: Annotated[Session, Depends(get_db)],
) -> SocialOAuthCallbackResponse:
    pending = SocialOAuthStateService(
        Redis.from_url(settings.redis_url), settings.social_oauth_state_ttl_seconds
    ).consume(state)
    if pending is None or pending.platform is not platform:
        raise HTTPException(status_code=400, detail="État OAuth invalide ou expiré.")
    publisher = _publisher(platform)
    try:
        grants = publisher.exchange_code(code, _callback_uri(settings, platform))
        connections, channels = persist_oauth_grants(
            db,
            pending,
            grants,
            SocialCredentialCipher(settings.social_credentials_key),
        )
    except SocialPublisherError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SocialOAuthCallbackResponse(connections=connections, channels=channels)


@workspace_router.get("", response_model=list[SocialConnectionResponse])
def list_social_connections(
    workspace_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership,
        Depends(require_workspace_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> list[SocialConnection]:
    return list(
        db.scalars(
            select(SocialConnection)
            .where(SocialConnection.workspace_id == workspace_id)
            .order_by(SocialConnection.created_at.desc())
        )
    )


@workspace_router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_social_connection(
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership,
        Depends(require_workspace_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    connection = db.scalar(
        select(SocialConnection).where(
            SocialConnection.id == connection_id,
            SocialConnection.workspace_id == workspace_id,
        )
    )
    if connection is None or connection.status is SocialConnectionStatus.REVOKED:
        raise HTTPException(status_code=404, detail="Connexion sociale introuvable.")
    connection.status = SocialConnectionStatus.REVOKED
    connection.revoked_at = datetime.now(timezone.utc)
    for channel in db.scalars(
        select(Channel).where(
            Channel.workspace_id == workspace_id,
            Channel.connection_id == connection.id,
        )
    ):
        channel.status = ChannelStatus.REVOKED
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
