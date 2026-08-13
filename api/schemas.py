"""Contrats HTTP du backend SaaS."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator, model_validator

from api.models import (
    ChannelPlatform,
    ChannelStatus,
    JobStatus,
    JobType,
    VideoStatus,
    WorkspaceRole,
)


class OTPRequest(BaseModel):
    email: EmailStr


class OTPVerify(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{6}$")


class GoogleLogin(BaseModel):
    credential: str = Field(min_length=20)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    avatar_url: str | None
    email_verified: bool


class WorkspaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: WorkspaceRole
    created_at: datetime


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ChannelCreate(BaseModel):
    platform: ChannelPlatform
    external_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    handle: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=2048)


class ChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    handle: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=2048)


class ChannelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    platform: ChannelPlatform
    external_id: str
    name: str
    handle: str | None
    avatar_url: str | None
    status: ChannelStatus
    created_at: datetime
    updated_at: datetime


class VideoCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    source_url: HttpUrl | None = None
    storage_key: str | None = Field(default=None, min_length=1, max_length=1024)

    @field_validator("storage_key")
    @classmethod
    def validate_storage_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("La clé de stockage doit être relative et ne pas contenir '..'.")
        return normalized

    @model_validator(mode="after")
    def require_video_source(self):
        if self.source_url is None and self.storage_key is None:
            raise ValueError("Une URL source ou une clé de stockage est obligatoire.")
        return self


class VideoUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class VideoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str | None
    source_url: str | None
    storage_key: str | None
    mime_type: str | None
    duration_seconds: float | None
    status: VideoStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class JobCreate(BaseModel):
    type: JobType
    video_id: uuid.UUID | None = None
    payload: dict | None = None

    @model_validator(mode="after")
    def require_video_for_pipeline_job(self):
        if self.type is not JobType.INGEST and self.video_id is None:
            raise ValueError("Une vidéo est obligatoire pour ce type de job.")
        return self


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    video_id: uuid.UUID | None
    type: JobType
    status: JobStatus
    progress: int
    attempts: int
    max_attempts: int
    payload: dict | None
    result: dict | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    updated_at: datetime
