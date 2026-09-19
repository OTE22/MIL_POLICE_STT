from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.enums import WorkstationStatus


class WorkstationOut(BaseModel):
    id: uuid.UUID
    agent_id: str
    device_name: str | None
    agent_version: str | None
    stt_provider: str | None
    stt_model: str | None
    stt_model_revision: str | None
    diarization_provider: str | None
    diarization_model: str | None
    diarization_model_revision: str | None
    processing_device: str | None
    gpu_name: str | None
    status: WorkstationStatus
    last_seen_at: datetime | None
    registered_by: uuid.UUID | None
    registered_by_name: str | None = None
    created_at: datetime


class AuditLogOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    username: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    safe_metadata: dict | None
    ip_address: str | None
    created_at: datetime


class AuditListOut(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    page_size: int


class ConfigFieldOut(BaseModel):
    """One runtime-tunable setting, with everything the interface needs to render it.

    Labels and help text ship from the backend so the WHITELIST and its wording live in one
    place - the frontend renders whatever arrives and can never invent an editable field.
    """

    key: str
    group: str
    label: str
    description: str
    type: str  # "int" | "float" | "bool" | "select" | "text"
    # bool must come FIRST: bool is a subclass of int, so a `str | int | float` union would
    # coerce True to 1 and the checkbox would render as a number field.
    value: bool | str | int | float
    min: float | None = None
    max: float | None = None
    options: list[str] | None = None


class ConfigOut(BaseModel):
    fields: list[ConfigFieldOut]


class ConfigUpdateIn(BaseModel):
    values: dict[str, str | int | float]
