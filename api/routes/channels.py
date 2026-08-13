"""Gestion des chaînes de publication d'un workspace."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies import get_current_workspace_membership, require_workspace_roles
from api.models import Channel, ChannelStatus, WorkspaceMembership, WorkspaceRole
from api.schemas import ChannelCreate, ChannelResponse, ChannelUpdate

router = APIRouter(prefix="/workspaces/{workspace_id}/channels", tags=["channels"])


def _get_channel(db: Session, workspace_id: uuid.UUID, channel_id: uuid.UUID) -> Channel:
    channel = db.scalar(
        select(Channel).where(
            Channel.id == channel_id,
            Channel.workspace_id == workspace_id,
        )
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Chaîne introuvable.")
    return channel


@router.get("", response_model=list[ChannelResponse])
def list_channels(
    workspace_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> list[Channel]:
    return list(
        db.scalars(
            select(Channel)
            .where(Channel.workspace_id == workspace_id)
            .order_by(Channel.created_at)
        )
    )


@router.get("/{channel_id}", response_model=ChannelResponse)
def get_channel(
    workspace_id: uuid.UUID,
    channel_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Channel:
    return _get_channel(db, workspace_id, channel_id)


@router.post("", response_model=ChannelResponse, status_code=status.HTTP_201_CREATED)
def create_channel(
    workspace_id: uuid.UUID,
    payload: ChannelCreate,
    membership: Annotated[
        WorkspaceMembership,
        Depends(require_workspace_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Channel:
    channel = Channel(workspace_id=workspace_id, **payload.model_dump())
    db.add(channel)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cette chaîne est déjà connectée.") from exc
    db.refresh(channel)
    return channel


@router.patch("/{channel_id}", response_model=ChannelResponse)
def update_channel(
    workspace_id: uuid.UUID,
    channel_id: uuid.UUID,
    payload: ChannelUpdate,
    membership: Annotated[
        WorkspaceMembership,
        Depends(require_workspace_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Channel:
    channel = _get_channel(db, workspace_id, channel_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(channel, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(channel)
    return channel


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_channel(
    workspace_id: uuid.UUID,
    channel_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership,
        Depends(require_workspace_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    channel = _get_channel(db, workspace_id, channel_id)
    channel.status = ChannelStatus.REVOKED
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
