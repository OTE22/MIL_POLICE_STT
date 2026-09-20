from __future__ import annotations

from app.schemas.person import PersonInput

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class VoiceEnrollmentCreate(PersonInput):
    """Enroll an identified speaker. The server resolves their person UUID and name."""

    notes: str | None = Field(default=None, max_length=2000)
    model: str | None = Field(default=None, max_length=200)
    model_revision: str | None = Field(default=None, max_length=100)
    provider: str | None = Field(default=None, max_length=100)
    sample_seconds: float | None = Field(default=None, ge=0)
    # Enrolling biometric data requires an explicit, recorded consent decision.
    consent_recorded: bool = False


class VoiceEnrollmentUpdate(PersonInput):
    # Canonical identity fields. They live on the person, not the print, so they may only be
    # changed with apply_to_person=true - otherwise one person's prints could disagree about
    # who they belong to.
    person_name: str | None = Field(default=None, max_length=200)
    apply_to_person: bool = False
    # Per-print fields, always scoped to the row addressed.
    notes: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None


class VoiceEnrollmentOut(BaseModel):
    """Enrolment metadata. The embedding itself is deliberately never exposed."""

    id: uuid.UUID
    # CURRENT canonical identity, resolved through identity_id. Anything showing "who this
    # person is" must use these.
    identity_id: uuid.UUID | None = None
    person_name: str
    # What was recorded when the print was taken. History: never overrides the registry, and
    # never rewritten when the canonical identity changes.
    enrolled_person_name: str | None = None
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


class PersonSearchOut(BaseModel):
    """A canonical identity that can be reused when identifying a speaker.

    Every aggregate here is computed over sessions the caller may access. The identity itself
    is deliberately visible - reusing it is the whole point of the registry - but its activity
    is not: "12 sessions" would tell an investigator with access to one that eleven others
    exist, which is the same leak as returning their numbers.
    """

    identity_id: uuid.UUID
    person_name: str
    accessible_session_count: int = 0
    accessible_print_count: int = 0
    accessible_sample_seconds: float = 0.0


class EnrollmentCandidateOut(BaseModel):
    """A speaker whose person is known and whose voice is ready to enrol."""

    speaker_id: uuid.UUID
    session_id: uuid.UUID
    session_number: str
    session_title: str | None = None
    speaker_label: str
    # The session-local label, for showing WHICH speaker this is. May carry a rank.
    display_name: str
    # The canonical registry name - the only value enrolment may assert as person_name.
    person_name: str
    speaker_role: str
    identity_id: uuid.UUID
    sample_seconds: float | None = None
    # never_enrolled | enrolled_inactive  (actively enrolled speakers are not candidates)
    enrollment_state: str
    inactive_enrollment_id: uuid.UUID | None = None
    created_at: datetime


class IdentityConsolidateIn(BaseModel):
    """Merge one canonical identity into another. No voice print need exist."""

    into_identity_id: uuid.UUID



class BiometricPrintCheckOut(BaseModel):
    """One print's standing among ITS OWN person's other prints. Never the vector."""

    enrollment_id: uuid.UUID
    created_at: datetime
    source_session_id: uuid.UUID | None
    source_speaker_label: str | None
    model: str
    embedding_dim: int
    sample_seconds: float | None
    peer_similarity_max: float | None
    peer_similarity_min: float | None
    coherent_peer_count: int
    # Component index within this (model, dim) group, 1-based. Two components = the
    # person's prints fall into internally-coherent sets that do NOT match each other.
    component_id: int
    status: str  # SINGLE_PRINT | NEAR_DUPLICATE | COHERENT | ISOLATED
    updated_at: datetime
    review_status: str = "NONE"


class BiometricPairOut(BaseModel):
    first_id: uuid.UUID
    second_id: uuid.UUID
    similarity: float


class BiometricGroupOut(BaseModel):
    """Prints are only comparable within one (model, embedding_dim); each such group is
    analysed on its own and reported separately."""

    model: str
    embedding_dim: int
    model_revision: str | None = None
    provider: str | None = None
    component_count: int
    prints: list[BiometricPrintCheckOut]
    pairs: list[BiometricPairOut] = Field(default_factory=list)


class VoiceIdentityConfirmationOut(BaseModel):
    id: uuid.UUID
    enrollment_ids: list[uuid.UUID]
    reason: str
    reviewer_name: str | None
    created_at: datetime
    status: Literal["ACTIVE", "STALE", "REOPENED"]
    reopened_reason: str | None = None
    reopened_by_name: str | None = None
    reopened_at: datetime | None = None


class VoiceConfirmationPrintIn(BaseModel):
    enrollment_id: uuid.UUID
    expected_updated_at: datetime


class VoiceIdentityConfirmationIn(BaseModel):
    prints: list[VoiceConfirmationPrintIn] = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=1, max_length=2000)


class VoiceConfirmationReopenIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class BiometricCheckOut(BaseModel):
    identity_id: uuid.UUID
    person_name: str
    total_active_prints: int
    number_of_components: int
    overall_status: str  # NO_PRINTS | SINGLE_PRINT | COHERENT | REVIEW_REQUIRED
    coherence_threshold: float
    near_duplicate_threshold: float
    groups: list[BiometricGroupOut]
    identity_confirmations: list[VoiceIdentityConfirmationOut] = Field(default_factory=list)


class VoiceReviewIn(BaseModel):
    action: Literal["NOTE", "FLAG", "RESOLVE", "DEACTIVATE"]
    reason: str = Field(min_length=1, max_length=2000)
    expected_updated_at: datetime
    identity_id: uuid.UUID


class VoiceReviewOut(BaseModel):
    id: uuid.UUID
    enrollment_id: uuid.UUID
    action: str
    reason: str
    reviewer_name: str | None
    created_at: datetime


class VoiceSourceSegmentOut(BaseModel):
    start_seconds: float
    end_seconds: float


class VoiceSourceOut(BaseModel):
    recording_id: uuid.UUID
    transcript_id: uuid.UUID
    segments: list[VoiceSourceSegmentOut]
