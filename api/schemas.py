"""Contrats HTTP du backend SaaS."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from api.models import WorkspaceRole


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
