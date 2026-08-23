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
