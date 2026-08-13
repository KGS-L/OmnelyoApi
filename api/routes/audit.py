"""Consultation administrative du journal d'audit d'un workspace."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies import require_workspace_roles
from api.models import AuditEvent, WorkspaceMembership, WorkspaceRole
from api.schemas import AuditEventResponse

router = APIRouter(prefix="/workspaces/{workspace_id}/audit-events", tags=["audit"])


@router.get("", response_model=list[AuditEventResponse])
def list_audit_events(
    workspace_id: uuid.UUID,
    membership: Annotated[
        WorkspaceMembership,
        Depends(require_workspace_roles(WorkspaceRole.OWNER, WorkspaceRole.ADMIN)),
    ],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[AuditEvent]:
    return list(
        db.scalars(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == workspace_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
