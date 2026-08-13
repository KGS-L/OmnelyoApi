"""Endpoints web de liaison et révocation de Telegram."""
import uuid
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import APISettings, get_settings
from api.database import get_db
from api.dependencies import get_current_user, get_current_workspace_membership
from api.integrations.telegram import TelegramLinkService
from api.models import (
    TelegramConnection,
    TelegramConnectionStatus,
    User,
    WorkspaceMembership,
)
from api.schemas import TelegramConnectionResponse, TelegramLinkResponse

router = APIRouter(
    prefix="/workspaces/{workspace_id}/integrations/telegram",
    tags=["integrations"],
)


def _get_connection(
    db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> TelegramConnection | None:
    return db.scalar(
        select(TelegramConnection).where(
            TelegramConnection.workspace_id == workspace_id,
            TelegramConnection.user_id == user_id,
        )
    )


@router.post("/link", response_model=TelegramLinkResponse)
def create_telegram_link(
    workspace_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[APISettings, Depends(get_settings)],
) -> TelegramLinkResponse:
    if not settings.telegram_bot_username:
        raise HTTPException(status_code=503, detail="Le bot Telegram n'est pas configuré.")
    redis = Redis.from_url(settings.redis_url)
    token = TelegramLinkService(redis, settings.telegram_link_ttl_seconds).issue(
        user.id, workspace_id
    )
    start_parameter = quote(f"link_{token}", safe="_-")
    return TelegramLinkResponse(
        url=f"https://t.me/{settings.telegram_bot_username}?start={start_parameter}",
        expires_in=settings.telegram_link_ttl_seconds,
        instructions=[
            "Ouvrez le lien Telegram.",
            "Appuyez sur Démarrer dans le bot ShortPilot.",
            "Revenez dans ShortPilot pour vérifier la connexion.",
        ],
    )


@router.get("", response_model=TelegramConnectionResponse)
def get_telegram_connection(
    workspace_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TelegramConnection:
    connection = _get_connection(db, workspace_id, user.id)
    if not connection or connection.status is not TelegramConnectionStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Telegram n'est pas connecté.")
    return connection


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def revoke_telegram_connection(
    workspace_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    connection = _get_connection(db, workspace_id, user.id)
    if not connection or connection.status is not TelegramConnectionStatus.ACTIVE:
        raise HTTPException(status_code=404, detail="Telegram n'est pas connecté.")
    connection.status = TelegramConnectionStatus.REVOKED
    connection.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
