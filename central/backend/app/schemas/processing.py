"""Schemas exchanged with the frontend (token issue) and the Local AI Agent (sync)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import JobStatus, RecordingSource

# Local Agent job states (section 50 of the specification).
AGENT_STATES = (
    "CREATED",
    "RECEIVING_AUDIO",
    "PREPROCESSING",
    "DIARIZING",
    "TRANSCRIBING",
    "FINALIZING",
    "SYNCING",
    "COMPLETED",
    "FAILED",
    "CANCELLED",
)


class ProcessingTokenRequest(BaseModel):
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(ge=1)
    source: RecordingSource = RecordingSource.FILE_UPLOAD


class ProcessingTokenOut(BaseModel):
    job_id: uuid.UUID
    recording_id: uuid.UUID
    session_id: uuid.UUID
    processing_token: str
    accept_by: datetime
    expires_at: datetime
    allowed_action: str
    speaker_limit_warning: bool


class WorkstationInfo(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    device_name: str | None = Field(default=None, max_length=200)
    agent_version: str | None = Field(default=None, max_length=50)
    stt_provider: str | None = Field(default=None, max_length=100)
    stt_model: str | None = Field(default=None, max_length=200)
    stt_model_revision: str | None = Field(default=None, max_length=100)
    diarization_provider: str | None = Field(default=None, max_length=100)
    diarization_model: str | None = Field(default=None, max_length=200)
    diarization_model_revision: str | None = Field(default=None, max_length=100)
    processing_device: str | None = Field(default=None, max_length=50)
    gpu_name: str | None = Field(default=None, max_length=200)
    stt_ready: bool | None = None
    diarization_ready: bool | None = None


class JobStateReport(BaseModel):
    state: str
    progress: float | None = Field(default=None, ge=0, le=1)
    message: str | None = Field(default=None, max_length=1000)
    failure_stage: str | None = Field(default=None, max_length=40)
    workstation: WorkstationInfo | None = None

    @field_validator("state")
    @classmethod
    def _state(cls, value: str) -> str:
        value = value.upper()
        if value not in AGENT_STATES:
            raise ValueError("invalid_state")
        return value


class SegmentIn(BaseModel):
    speaker_label: str = Field(pattern=r"^SPEAKER_\d{2}$")
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(ge=0)
    text: str = Field(max_length=20000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    is_overlap: bool = False

    @field_validator("end_seconds")
    @classmethod
    def _end_after_start(cls, value: float, info):  # noqa: ANN001
        start = info.data.get("start_seconds")
        if start is not None and value < start:
            raise ValueError("end_before_start")
        return value


class AudioMetadataIn(BaseModel):
    original_filename: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=100)
    size_bytes: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class VoiceSpeakerEmbeddingIn(BaseModel):
    embedding: list[float] = Field(min_length=16, max_length=1024)
    seconds: float | None = Field(default=None, ge=0)


class VoiceIdentificationIn(BaseModel):
    """Voice embeddings produced locally by SpeakerNet-M. Names are never sent by the agent."""

    provider: str = Field(max_length=100)
    model: str = Field(max_length=200)
    model_revision: str | None = Field(default=None, max_length=100)
    embedding_dim: int = Field(ge=16, le=1024)
    device: str | None = Field(default=None, max_length=50)
    speakers: dict[str, VoiceSpeakerEmbeddingIn] = Field(default_factory=dict)


class ProcessingResultIn(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    language: str = Field(default="ar", max_length=10)
    stt_provider: str = Field(max_length=100)
    stt_model: str = Field(max_length=200)
    stt_model_revision: str | None = Field(default=None, max_length=100)
    diarization_provider: str = Field(max_length=100)
    diarization_model: str = Field(max_length=200)
    diarization_model_revision: str | None = Field(default=None, max_length=100)
    vad_model: str | None = Field(default=None, max_length=200)
    agent_version: str = Field(max_length=50)
    processing_device: str = Field(max_length=50)
    speaker_count: int = Field(ge=0, le=20)
    warnings: list[str] = Field(default_factory=list)
    processing_metadata: dict = Field(default_factory=dict)
    audio: AudioMetadataIn | None = None
    workstation: WorkstationInfo | None = None
    voice_identification: VoiceIdentificationIn | None = None
    segments: list[SegmentIn]
    completed_at: datetime | None = None


class ProcessingResultOut(BaseModel):
    job_id: uuid.UUID
    transcript_id: uuid.UUID
    status: JobStatus
    duplicate: bool = False
    audio_upload_expected: bool = True


class JobOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    recording_id: uuid.UUID
    status: JobStatus
    agent_state: str | None
    failure_stage: str | None
    error_message: str | None
    idempotency_key: str | None
    token_accept_by: datetime
    token_expires_at: datetime
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    workstation_agent_id: str | None = None


class PublicKeyOut(BaseModel):
    algorithm: str
    key_id: str
    issuer: str
    audience: str
    public_key_pem: str
