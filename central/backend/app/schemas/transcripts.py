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
    # Canonical identity. Serialized outbound only - SpeakerUpdateIn deliberately has no
    # identity_id, so a client can never attach a speaker to another person by UUID.
    identity_id: uuid.UUID | None = None
    # The canonical person behind identity_id. display_name is a session-local label and
    # may be empty even when the speaker IS identified, so enrolment reads these instead.
    identity_name: str | None = None
    identity_reference: str | None = None


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
    # The canonical human name, rank EXCLUDED - the only field here that speaks for the
    # registry. display_name is a session-local label: it may carry a rank, a nickname or
    # nothing at all, so it must never become person_identities.person_name.
    #
    # Sent only when the client actually knows who this is (an exact participant selection,
    # or the identification dialog), never re-sent to re-prove an identity the server already
    # resolved. Still no identity_id: identity stays backend-owned, resolved from
    # reference_number.
    person_name: str | None = Field(default=None, max_length=200)
