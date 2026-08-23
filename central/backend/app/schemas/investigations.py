from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AssignmentRole, RecordingSource, RecordingUploadStatus, SessionStatus

# The NVIDIA Sortformer 4spk model supports at most four speakers.
MAX_SUPPORTED_SPEAKERS = 4


class InvestigatorAssignmentIn(BaseModel):
    investigator_id: uuid.UUID
    assignment_role: AssignmentRole = AssignmentRole.ASSISTANT


class SubjectIn(BaseModel):
    subject_name: str | None = Field(default=None, max_length=200)
    reference_number: str | None = Field(default=None, max_length=100)
    military_id: str | None = Field(default=None, max_length=64)
    rank: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)


class SubjectOut(SubjectIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


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


class InvestigatorBrief(BaseModel):
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
