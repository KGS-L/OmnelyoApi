"""Contrats HTTP du backend SaaS."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from api.models import ChannelPlatform, ChannelStatus, WorkspaceRole


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
