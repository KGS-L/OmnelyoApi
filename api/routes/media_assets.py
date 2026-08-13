"""Upload et consultation des images réutilisables dans les publications."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.config import APISettings, get_settings
from api.database import get_db
from api.dependencies import get_current_workspace_membership
from api.media_upload import detect_image_type, image_dimensions, stream_image_upload
from api.models import MediaAsset, MediaAssetType, WorkspaceMembership
from api.quota_service import QuotaExceeded, QuotaService
from api.schemas import MediaAssetResponse
from core.storage_keys import media_asset_key

router = APIRouter(prefix="/workspaces/{workspace_id}/media-assets", tags=["media-assets"])


@router.post("/upload", response_model=MediaAssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_media_asset(
    workspace_id: uuid.UUID,
    membership: Annotated[WorkspaceMembership, Depends(get_current_workspace_membership)],
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[APISettings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
) -> MediaAsset:
    from core.storage_r2 import delete_from_r2, upload_to_r2
    import config

    asset_id = uuid.uuid4()
    temporary = config.TMP_DIR / "workspaces" / str(workspace_id) / "uploads" / f"{asset_id}.part"
    storage_key = None
    try:
        size_bytes = await stream_image_upload(file, temporary, settings.image_upload_max_bytes)
        with temporary.open("rb") as uploaded:
            mime_type, suffix = detect_image_type(uploaded.read(32))
        width, height = image_dimensions(temporary, mime_type)
        quota = QuotaService()
        quota.ensure_storage_available(db, workspace_id, size_bytes)
        storage_key = media_asset_key(workspace_id, asset_id, suffix)
        upload_to_r2(temporary, storage_key)
        asset = MediaAsset(
            id=asset_id,
            workspace_id=workspace_id,
            type=MediaAssetType.IMAGE,
            storage_key=storage_key,
            mime_type=mime_type,
            size_bytes=size_bytes,
            width=width,
            height=height,
            retention_expires_at=quota.retention_deadline(db, workspace_id),
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset
    except QuotaExceeded as exc:
        db.rollback()
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        if storage_key:
            try:
                delete_from_r2(storage_key)
            except RuntimeError:
                pass
        raise
    finally:
        temporary.unlink(missing_ok=True)


@router.get("", response_model=list[MediaAssetResponse])
def list_media_assets(
    workspace_id: uuid.UUID,
    membership: Annotated[WorkspaceMembership, Depends(get_current_workspace_membership)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MediaAsset]:
    return list(db.scalars(
        select(MediaAsset)
        .where(MediaAsset.workspace_id == workspace_id)
        .order_by(MediaAsset.created_at.desc())
        .limit(limit)
        .offset(offset)
    ))
