from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import IdentificationStatus, SpeakerRole, TranscriptStatus


class SegmentOut(BaseModel):
    id: uuid.UUID
    sequence: int
    speaker_label: str
    start_seconds: float
    end_seconds: float
    original_text: str
    edited_text: str | None
    confidence: float | None
    is_overlap: bool
    edited_by: uuid.UUID | None
    edited_by_name: str | None = None
    edited_at: datetime | None


class SpeakerOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    speaker_label: str
    display_name: str | None
    speaker_role: SpeakerRole
    reference_number: str | None
    notes: str | None
    segment_count: int = 0
    total_seconds: float = 0.0
    updated_at: datetime
    # Voice-based suggestion (never applied automatically).
    identification_status: IdentificationStatus = IdentificationStatus.NONE
    suggested_name: str | None = None
    suggested_score: float | None = None
    suggested_model: str | None = None
    has_voice_embedding: bool = False


class TranscriptOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    recording_id: uuid.UUID
    job_id: uuid.UUID
    status: TranscriptStatus
    language: str
    stt_provider: str | None
    stt_model: str | None
    stt_model_revision: str | None
    diarization_provider: str | None
    diarization_model: str | None
    diarization_model_revision: str | None
    vad_model: str | None
    agent_version: str | None
    processing_device: str | None
    speaker_count: int | None
    warnings: list[str]
    created_at: datetime
    completed_at: datetime | None
    audio_available: bool
    segments: list[SegmentOut]
    speakers: list[SpeakerOut]


class SegmentEditIn(BaseModel):
    edited_text: str = Field(max_length=20000)


class SpeakerUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    speaker_role: SpeakerRole | None = None
    reference_number: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
