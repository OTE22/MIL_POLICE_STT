"""Wire shapes for the محضر تحقيق composer.

The composer edits CONTENT: which recordings, which text, the header fields, the wording of
each س/ج. It never carries layout - fonts, margins, letterhead and signature positions
belong to the Word template and deliberately have no representation here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, Field

from app.models import FushaStatus, ReportStatus, TranscriptSourceMode


class QABlockOut(BaseModel):
    id: uuid.UUID
    sequence: int
    # What the transcript said (a copy taken when the block was built) beside what will be
    # printed - the composer shows both, so an edit is always visible as an edit.
    question_source_text: str | None
    answer_source_text: str | None
    report_question_text: str | None
    report_answer_text: str | None
    question_speaker_id: uuid.UUID | None
    answer_speaker_id: uuid.UUID | None
    question_speaker_name: str | None
    answer_speaker_name: str | None
    answer_speaker_resolved: bool
    source_segment_ids: list[str]
    source_recording_ids: list[str]
    start_seconds: float | None
    end_seconds: float | None
    included_in_report: bool
    exclusion_reason: str | None
    fusha_status: FushaStatus
    llm_suggested_question: str | None
    llm_suggested_answer: str | None
    edited_at: datetime | None


class RecordingOptionOut(BaseModel):
    """One recording the report may include."""

    id: uuid.UUID
    index: int
    original_filename: str
    duration_seconds: float | None
    created_at: datetime
    has_transcript: bool
    selected: bool


class ReportSpeakerOut(BaseModel):
    """A voice in this session and whether the report may name a person for it."""

    id: uuid.UUID
    speaker_label: str
    source_label: str | None
    recording_id: uuid.UUID | None
    role: str
    display_name: str | None
    person_name: str | None
    resolved: bool
    legacy: bool
    report_name: str


class StalePinOut(BaseModel):
    recording_id: uuid.UUID
    transcript_id: uuid.UUID
    reason: str


class ReportDraftOut(BaseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    status: ReportStatus
    report_number: str | None
    case_subject: str | None
    report_date: date | None
    report_time: time | None
    location: str | None
    intro_text: str | None
    closing_text: str | None
    transcript_source_mode: TranscriptSourceMode
    unresolved_ack: bool
    updated_at: datetime
    qa_blocks: list[QABlockOut]
    recordings: list[RecordingOptionOut]
    speakers: list[ReportSpeakerOut]
    # Transcripts that changed after this draft was built. The composer offers
    # تحديث من النص المنقح; nothing rebuilds on its own.
    stale: list[StalePinOut]
    # Missing header fields, in Arabic - shown while drafting, enforced at finalization.
    missing_fields: list[str]
    unresolved_speaker_labels: list[str]
    report_version_count: int
    # Whether الصياغة بالفصحى can be offered on this machine. Absent AI is a normal state:
    # the composer simply shows a note and the investigator writes the wording themselves.
    llm: "LLMCapabilitiesBrief"


class ReportDraftUpdateIn(BaseModel):
    """Header fields and content selection. Absent keys are left as they are."""

    report_number: str | None = Field(default=None, max_length=100)
    case_subject: str | None = Field(default=None, max_length=500)
    report_date: date | None = None
    report_time: time | None = None
    location: str | None = Field(default=None, max_length=300)
    intro_text: str | None = Field(default=None, max_length=5000)
    closing_text: str | None = Field(default=None, max_length=5000)
    # Changing either of these re-quotes the evidence, so the server rebuilds the Q&A.
    transcript_source_mode: TranscriptSourceMode | None = None
    selected_recording_ids: list[uuid.UUID] | None = None
    # "I know speaker N has no identity and I am issuing the report anyway."
    unresolved_ack: bool | None = None


class QABlockUpdateIn(BaseModel):
    report_question_text: str | None = Field(default=None, max_length=20000)
    report_answer_text: str | None = Field(default=None, max_length=20000)


class QAExcludeIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class QASplitIn(BaseModel):
    """The composer knows where the cursor was; the server does not guess."""

    answer_head: str = Field(max_length=20000)
    answer_tail: str = Field(max_length=20000)


class QAMergeIn(BaseModel):
    """Merge this block with the one after it - diarization split one exchange in two."""

    with_block_id: uuid.UUID


class FushaSuggestIn(BaseModel):
    """Ask for a Fusha rewording of this block. Which halves, if not both."""

    question: bool = True
    answer: bool = True


class FushaDecisionIn(BaseModel):
    """The human's verdict on a suggestion.

    `accept` with no text adopts the suggestion as it stands; `accept` with text is the
    investigator's own edit of it. Rejecting keeps the suggestion on the record (so the
    trail shows what was offered and refused) but changes nothing that will be printed.
    """

    accept: bool
    report_question_text: str | None = Field(default=None, max_length=20000)
    report_answer_text: str | None = Field(default=None, max_length=20000)


class LLMCapabilitiesBrief(BaseModel):
    """What the composer needs to decide whether to offer the Fusha controls at all."""

    available: bool
    provider: str
    model: str | None
    fallback_reason: str | None


class GeneratedReportOut(BaseModel):
    """One ISSUED محضر. Immutable: a correction produces a new version, never an edit."""

    id: uuid.UUID
    report_version: int
    report_number: str | None
    template_version: int | None
    template_is_development: bool
    docx_sha256: str
    context_sha256: str | None
    template_sha256: str | None
    size_bytes: int | None
    qa_block_count: int | None
    transcript_source_mode: TranscriptSourceMode | None
    selected_recording_ids: list[str]
    pinned_transcripts: list[dict]
    generated_by: uuid.UUID | None
    generated_by_name: str | None
    created_at: datetime


class ReportArchiveOut(BaseModel):
    reports: list[GeneratedReportOut]
    # Why finalization would be refused right now - shown before the operator tries.
    can_finalize: bool
    blocked_reasons: list[str]
    missing_fields: list[str]
    unresolved_speaker_labels: list[str]
    active_template_version: int | None
    active_template_is_development: bool


class ReportVerificationOut(BaseModel):
    """Integrity verification, not a digital signature."""

    report_id: uuid.UUID
    ok: bool
    docx_ok: bool
    context_ok: bool
    template_ok: bool
    detail: str
