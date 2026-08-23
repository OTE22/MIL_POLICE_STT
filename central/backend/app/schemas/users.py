from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.core.permissions import ROLE_ADMIN, ROLE_INVESTIGATOR, ROLE_USER
from app.schemas.auth import InvestigatorProfileOut

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")
VALID_ROLES = {ROLE_ADMIN, ROLE_INVESTIGATOR, ROLE_USER}


class ProfileIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    rank: str | None = Field(default=None, max_length=100)
    military_id: str | None = Field(default=None, max_length=64)
    unit: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)


class UserCreate(BaseModel):
    username: str
    password: str = Field(min_length=10, max_length=256)
    roles: list[str] = Field(default_factory=lambda: [ROLE_USER])
    profile: ProfileIn
    must_change_password: bool = True

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        if not _USERNAME_RE.match(value):
            raise ValueError("invalid_username")
        return value.lower()

    @field_validator("roles")
    @classmethod
    def _roles(cls, value: list[str]) -> list[str]:
        value = [v.upper() for v in value]
        if not value or any(v not in VALID_ROLES for v in value):
            raise ValueError("invalid_role")
        return sorted(set(value))


class UserUpdate(BaseModel):
    roles: list[str] | None = None
    profile: ProfileIn | None = None

    @field_validator("roles")
    @classmethod
    def _roles(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        value = [v.upper() for v in value]
        if not value or any(v not in VALID_ROLES for v in value):
            raise ValueError("invalid_role")
        return sorted(set(value))


class UserStatusUpdate(BaseModel):
    is_active: bool


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=10, max_length=256)
    must_change_password: bool = True


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    is_active: bool
    must_change_password: bool
    roles: list[str]
    last_login_at: datetime | None
    created_at: datetime
    profile: InvestigatorProfileOut | None


class UserListOut(BaseModel):
    items: list[UserOut]
    total: int
