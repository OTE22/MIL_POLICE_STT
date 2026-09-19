"""Wire shapes for the official template registry (one format, many versions)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models import TemplateValidationStatus


class TemplateVersionOut(BaseModel):
    id: uuid.UUID
    version: int
    original_filename: str | None
    size_bytes: int | None
    sha256: str
    validation_status: TemplateValidationStatus
    validation_message: str | None
    # The bundled stand-in, not an approved official form.
    is_development: bool
    is_active: bool
    activated_at: datetime | None
    notes: str | None
    uploaded_by: uuid.UUID | None
    created_at: datetime
    # How many issued reports cite this version - such a version is never deleted.
    reports_issued: int


class TemplatesOut(BaseModel):
    active: TemplateVersionOut | None
    # False while the active template is the development stand-in or does not validate:
    # production refuses to issue an official document in that state.
    production_ready: bool
    environment: str
    versions: list[TemplateVersionOut]


class TemplatePlaceholdersOut(BaseModel):
    """What a template author may write. Anything else fails validation."""

    scalars: list[str]
    lists: list[str]
    required: list[str]
