from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class VoiceEnrollmentCreate(BaseModel):
    """Create a voice template from an already-identified speaker in a session."""

    person_reference: str = Field(min_length=1, max_length=100)
    person_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    model: str = Field(max_length=200)
    model_revision: str | None = Field(default=None, max_length=100)
    provider: str | None = Field(default=None, max_length=100)
    sample_seconds: float | None = Field(default=None, ge=0)
    # Enrolling biometric data requires an explicit, recorded consent decision.
    consent_recorded: bool = False


class VoiceEnrollmentUpdate(BaseModel):
    person_name: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class VoiceEnrollmentOut(BaseModel):
    """Enrolment metadata. The embedding itself is deliberately never exposed."""

    id: uuid.UUID
    person_name: str
    person_reference: str
    notes: str | None
    model: str
    model_revision: str | None
    provider: str | None
    embedding_dim: int
    sample_seconds: float | None
    source_session_id: uuid.UUID | None
    source_speaker_label: str | None
    consent_recorded: bool
    is_active: bool
    enrolled_by: uuid.UUID | None
    enrolled_by_name: str | None
    created_at: datetime
    updated_at: datetime


class SpeakerDecisionIn(BaseModel):
    """A human decision on a voice suggestion. `accept=True` writes display_name."""

    accept: bool
