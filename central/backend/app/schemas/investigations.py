from __future__ import annotations

from app.schemas.person import PersonInput

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    AssignmentRole,
    IdentityConfidence,
    PersonType,
    RecordingSource,
    RecordingUploadStatus,
    SecurityBranch,
    SessionStatus,
    SubjectDocumentType,
    UndocumentedReason,
)

# The NVIDIA Sortformer 4spk model supports at most four speakers.
MAX_SUPPORTED_SPEAKERS = 4


class InvestigatorAssignmentIn(BaseModel):
    investigator_id: uuid.UUID
    assignment_role: AssignmentRole = AssignmentRole.ASSISTANT


class SubjectDocumentIn(BaseModel):
    """An identity document presented by the subject. Everything is optional
    except the type, so a document can be recorded even when the number is unknown."""

    id: uuid.UUID | None = None  # present when updating an existing document
    document_type: SubjectDocumentType
    document_number: str | None = Field(default=None, max_length=100)
    issuing_country: str | None = Field(default=None, max_length=100)
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


class SubjectDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject_id: uuid.UUID
    document_type: SubjectDocumentType
    document_number: str | None
    issuing_country: str | None
    issue_date: date | None
    expiry_date: date | None
    notes: str | None
    # File metadata only; the scan itself is served by a separate authorized route.
    has_file: bool = False
    original_filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    uploaded_by: uuid.UUID | None = None
    uploaded_by_name: str | None = None
    created_at: datetime
    is_expired: bool = False


class SubjectIn(PersonInput):
    # The ONLY handle that identifies which existing participant this is. `Subject.id` is
    # deliberately absent: the save rebuilds every row, so an id is dead the moment it is
    # issued, and accepting one would invite a fallback that works once and then starts
    # issuing second references. The backend mints this and rejects a value it did not issue.
    # NOT a person identifier.
    participant_key: uuid.UUID | None = None
    identity_id: uuid.UUID | None = None
    # A person is recorded by NAME. It was optional, and the consequence was an identity
    # named after its own reference - one missing field silently becoming fake data.
    # Latin script is deliberately accepted: a passport or UNHCR paper may carry the only
    # spelling there is, and transliterating it would be inventing evidence.
    subject_name: str = Field(min_length=1, max_length=200)
    person_type: PersonType = PersonType.CIVILIAN
    # military
    military_id: str | None = Field(default=None, max_length=64)
    rank: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    security_branch: SecurityBranch | None = None
    # civilian
    nationality_code: str | None = Field(default=None, max_length=2, pattern=r"^[A-Za-z]{2}$")
    nationality_name: str | None = Field(default=None, max_length=100)
    register_number: str | None = Field(default=None, max_length=64)
    place_of_registration: str | None = Field(default=None, max_length=200)
    caza_code: str | None = Field(default=None, max_length=32)
    is_unregistered: bool = False
    # unidentified / undocumented
    is_undocumented: bool = False
    undocumented_reason: UndocumentedReason | None = None
    identity_confidence: IdentityConfidence = IdentityConfidence.DECLARED
    notes: str | None = Field(default=None, max_length=4000)
    documents: list[SubjectDocumentIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _military_must_be_identifiable(self):
        """A supplied service number needs its force to be useful identity evidence."""
        if self.person_type != PersonType.MILITARY:
            return self
        # A soldier whose serial is simply NOT KNOWN must stay recordable - an interview
        # happens even when their service details have not been established.
        if not (self.military_id or "").strip():
            return self
        # A serial WITHOUT a usable force is the incoherent case: it looks like identity
        # evidence and is not, because a serial is unique only within its force. OTHER is a
        # catch-all, not a namespace, so it cannot supply the missing half either.
        if self.security_branch is None or self.security_branch == SecurityBranch.OTHER:
            raise ValueError("military_id_needs_security_branch")
        return self

    @field_validator("subject_name")
    @classmethod
    def _real_name(cls, value: str) -> str:
        """Stored trimmed, and never whitespace pretending to be a name."""
        name = (value or "").strip()
        if not name:
            raise ValueError("subject_name_required")
        return name

    @field_validator("nationality_code")
    @classmethod
    def _upper_country(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    participant_key: uuid.UUID
    identity_id: uuid.UUID | None = None
    subject_name: str | None
    person_type: PersonType
    military_id: str | None
    rank: str | None
    unit: str | None
    department: str | None
    security_branch: SecurityBranch | None
    nationality_code: str | None
    nationality_name: str | None
    register_number: str | None
    place_of_registration: str | None
    caza_code: str | None = None
    is_unregistered: bool
    is_undocumented: bool
    undocumented_reason: UndocumentedReason | None
    identity_confidence: IdentityConfidence
    notes: str | None
    documents: list[SubjectDocumentOut] = Field(default_factory=list)
    # Warning shown when the same document number appears in another session.
    duplicate_of_sessions: list[str] = Field(default_factory=list)


class InvestigationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    session_number: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=8000)
    location: str | None = Field(default=None, max_length=300)
    session_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    notes: str | None = Field(default=None, max_length=8000)
    expected_speaker_count: int = Field(default=2, ge=1, le=20)
    investigators: list[InvestigatorAssignmentIn] = Field(default_factory=list)
    subjects: list[SubjectIn] = Field(default_factory=list)


class InvestigationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=8000)
    location: str | None = Field(default=None, max_length=300)
    session_date: date | None = None
    start_time: time | None = None
    end_time: time | None = None
    notes: str | None = Field(default=None, max_length=8000)
    expected_speaker_count: int | None = Field(default=None, ge=1, le=20)
    status: SessionStatus | None = None
    investigators: list[InvestigatorAssignmentIn] | None = None
    subjects: list[SubjectIn] | None = None
    # Participants the operator deliberately removed. Absence alone is ambiguous under
    # replacement semantics - it could equally mean the client lost the row - so deletion is
    # stated rather than inferred. Without it, "delete B and add C in one save" cannot be
    # told apart from "B's key went missing".
    removed_participant_keys: list[uuid.UUID] = Field(default_factory=list)


class SessionPersonOut(BaseModel):
    """One person on a session, in ONE shape, whatever kind of row they came from.

    The UI used to assemble this three different ways - a Subject, an InvestigatorBrief and a
    PersonSearchResult - each with its own idea of what "the name" is. The same human then
    rendered as "MAJOR ALI" in one section and "ALI" in another, and appeared twice because the
    de-duplication only knew about one of the sources.

    `person_name` is always the CANONICAL name from `person_identities`, resolved through any
    merge, so it is the registry's answer and not a copy that drifted. `rank` is display
    decoration carried separately - it belongs to the role, not the person, and must never be
    folded into a name that gets stored.
    """

    identity_id: uuid.UUID | None = None
    person_name: str
    rank: str | None = None
    # SUBJECT or INVESTIGATOR - which section of the picker this belongs under.
    source: str
    # Present for subjects: the session-local handle that survives reordering.
    participant_key: uuid.UUID | None = None
    identity_id: uuid.UUID | None = None
    # False when the row cannot be picked yet, with `blocked_reason` saying why.
    selectable: bool = True
    blocked_reason: str | None = None


class InvestigatorBrief(BaseModel):
    identity_id: uuid.UUID | None = None
    # Assignment registers the investigator as a person with a stable UUID.
    security_branch: SecurityBranch | None = None
    id: uuid.UUID
    full_name: str
    rank: str | None = None
    military_id: str | None = None
    unit: str | None = None
    department: str | None = None
    job_title: str | None = None
    assignment_role: AssignmentRole | None = None


class RecordingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    session_id: uuid.UUID
    original_filename: str
    mime_type: str
    size_bytes: int | None
    duration_seconds: float | None
    sha256: str | None
    source: RecordingSource
    upload_status: RecordingUploadStatus
    created_at: datetime


class InvestigationOut(BaseModel):
    id: uuid.UUID
    session_number: str
    title: str
    description: str | None
    location: str | None
    session_date: date | None
    start_time: time | None
    end_time: time | None
    status: SessionStatus
    notes: str | None
    expected_speaker_count: int
    speaker_limit_warning: bool
    created_by: uuid.UUID
    created_by_name: str | None
    created_at: datetime
    updated_at: datetime
    investigators: list[InvestigatorBrief]
    subjects: list[SubjectOut]
    recordings: list[RecordingOut] = Field(default_factory=list)
    latest_job_status: str | None = None
    has_transcript: bool = False
    duration_seconds: float | None = None


class InvestigationListItem(BaseModel):
    id: uuid.UUID
    session_number: str
    title: str
    location: str | None
    session_date: date | None
    status: SessionStatus
    lead_investigator: str | None
    duration_seconds: float | None
    created_at: datetime


class InvestigationListOut(BaseModel):
    items: list[InvestigationListItem]
    total: int
    page: int
    page_size: int


class DashboardOut(BaseModel):
    total_sessions: int
    sessions_today: int
    processing: int
    completed: int
    recent: list[InvestigationListItem]
