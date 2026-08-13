"""Consultation et administration des workspaces accessibles."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies import (
    get_current_user,
    get_current_workspace_membership,
    require_workspace_roles,
)
from api.models import User, Workspace, WorkspaceMembership, WorkspaceRole
from api.schemas import WorkspaceResponse, WorkspaceUpdate

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _response(workspace: Workspace, role: WorkspaceRole) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        role=role,
        created_at=workspace.created_at,
    )


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkspaceResponse]:
    rows = db.execute(
        select(Workspace, WorkspaceMembership.role)
        .join(
            WorkspaceMembership,
            WorkspaceMembership.workspace_id == Workspace.id,
        )
        .where(WorkspaceMembership.user_id == user.id)
        .order_by(Workspace.created_at)
    ).all()
    return [_response(workspace, role) for workspace, role in rows]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership, Depends(get_current_workspace_membership)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceResponse:
    workspace = db.get(Workspace, workspace_id)
    return _response(workspace, membership.role)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdate,
    membership: Annotated[
        WorkspaceMembership,
        Depends(require_workspace_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> WorkspaceResponse:
    workspace = db.get(Workspace, workspace_id)
    workspace.name = payload.name.strip()
    db.commit()
    db.refresh(workspace)
    return _response(workspace, membership.role)
