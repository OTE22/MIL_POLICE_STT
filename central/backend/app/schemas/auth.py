from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SecurityBranch


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class InvestigatorProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    rank: str | None = None
    military_id: str | None = None
    security_branch: SecurityBranch | None = None
    # Null until they are assigned to a session, which is when they are registered as a person.
    reference_number: str | None = None
    unit: str | None = None
    department: str | None = None
    job_title: str | None = None
    phone: str | None = None
    email: str | None = None
    location: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class CurrentUserOut(BaseModel):
    id: uuid.UUID
    username: str
    is_active: bool
    must_change_password: bool
    roles: list[str]
    permissions: list[str]
    last_login_at: datetime | None = None
    profile: InvestigatorProfileOut | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=10, max_length=256)
