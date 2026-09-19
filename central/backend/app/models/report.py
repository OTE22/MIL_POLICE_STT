"""محضر تحقيق: the official investigation report — draft, Q&A, template versions, archive.

Four tables, one purpose each, and the boundaries between them are the point:

  report_template_versions  the ORGANISATION's layout. One official format, versioned.
  report_drafts             the INVESTIGATOR's working copy for one session. Mutable.
  report_qa_blocks          the dialogue as it will be printed. Mutable while DRAFT.
  generated_reports         what was actually issued. Immutable, hashed, never overwritten.

The report is a DERIVED document. Nothing here may write back to recordings, transcripts,
speakers, identities or voice prints - report editing changes the report only. Q&A blocks
therefore COPY their source text rather than reading through to transcript_segments at
render time: a transcript corrected next month must not silently alter a محضر submitted
today.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ReportStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"


class TranscriptSourceMode(str, enum.Enum):
    """Which text of the transcript the report quotes."""

    # Human correction where one exists, the AI text elsewhere. The default.
    CORRECTED = "CORRECTED"
    # The untouched machine transcript only.
    ORIGINAL = "ORIGINAL"


class TemplateValidationStatus(str, enum.Enum):
    UNVALIDATED = "UNVALIDATED"
    VALID = "VALID"
    INVALID = "INVALID"


class FushaStatus(str, enum.Enum):
    """Where one Q&A block stands in the optional Arabic-formalization review."""

    NOT_REQUESTED = "NOT_REQUESTED"
    AI_SUGGESTED = "AI_SUGGESTED"
    HUMAN_EDITED = "HUMAN_EDITED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReportTemplateVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One version of THE official Word template.

    There is exactly one official format; this table gives it a history. Only one version is
    active for new reports, and a version referenced by a generated report is never deleted -
    a report issued last year must still name the layout it was printed on.
    """

    __tablename__ = "report_template_versions"
    __table_args__ = (UniqueConstraint("version", name="uq_report_template_version"),)

    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Relative to CENTRAL_STORAGE_ROOT: report-templates/{id}.docx
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[TemplateValidationStatus] = mapped_column(
        Enum(TemplateValidationStatus, name="template_validation_status"),
        nullable=False,
        default=TemplateValidationStatus.UNVALIDATED,
    )
    validation_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The bundled development template is NOT an approved official form. Production refuses
    # to finalize on it; tests and UI development use it freely.
    is_development: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ReportDraft(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The investigator's working محضر for one session (one draft per session)."""

    __tablename__ = "report_drafts"
    __table_args__ = (UniqueConstraint("session_id", name="uq_report_draft_session"),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[ReportStatus] = mapped_column(
        Enum(ReportStatus, name="report_status"), nullable=False, default=ReportStatus.DRAFT
    )

    # ---- header fields the investigator fills ------------------------------
    report_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    case_subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    report_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    intro_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    closing_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- content selection --------------------------------------------------
    transcript_source_mode: Mapped[TranscriptSourceMode] = mapped_column(
        Enum(TranscriptSourceMode, name="transcript_source_mode"),
        nullable=False,
        default=TranscriptSourceMode.CORRECTED,
    )
    # [recording_id, ...] as strings, chronological order enforced at build time.
    selected_recording_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # The exact transcripts this draft was built from:
    # [{recording_id, transcript_id, segments_sha256, built_at}]. There is no revision
    # counter on transcripts, so the sha256 of the segments' effective text IS the revision:
    # it changes the moment anyone edits a line, which is how a stale draft is detected.
    pinned_transcripts: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # A human ticked "yes, I know speaker N has no identity" - required to finalize.
    unresolved_ack: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    unresolved_ack_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    unresolved_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    qa_blocks: Mapped[list[ReportQABlock]] = relationship(
        "ReportQABlock",
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="ReportQABlock.sequence",
        lazy="selectin",
    )


class ReportQABlock(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One س/ج pair as it will be printed, with a link back to the evidence it came from."""

    __tablename__ = "report_qa_blocks"
    __table_args__ = (UniqueConstraint("draft_id", "sequence", name="uq_report_qa_sequence"),)

    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("report_drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    # What the transcript said when this block was built. A COPY, deliberately: the report
    # must be able to show "source vs printed" years later, and must not change when the
    # transcript is corrected afterwards.
    question_source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answer_source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What will actually be printed (edited by the investigator, optionally AI-assisted).
    report_question_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Attribution: the speaker OBSERVATIONS (recording-local) these turns came from.
    question_speaker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("session_speakers.id", ondelete="SET NULL"), nullable=True
    )
    answer_speaker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("session_speakers.id", ondelete="SET NULL"), nullable=True
    )
    # Provenance, kept as ids rather than FKs so the block survives evidence retention moves.
    source_segment_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_recording_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    start_seconds: Mapped[float | None] = mapped_column(nullable=True)
    end_seconds: Mapped[float | None] = mapped_column(nullable=True)

    # Report-level exclusion (mic tests, greetings, side conversation). The EVIDENCE is never
    # deleted - only this block's inclusion in the printed document changes.
    included_in_report: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    exclusion_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    excluded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    excluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ---- optional Arabic formalization (advisory; a human always decides) ----
    fusha_status: Mapped[FushaStatus] = mapped_column(
        Enum(FushaStatus, name="fusha_status"),
        nullable=False,
        default=FushaStatus.NOT_REQUESTED,
        server_default="NOT_REQUESTED",
    )
    llm_suggested_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_suggested_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # {source_text_hash, provider, runtime, model, temperature, generated_at,
    #  approved_by, approved_at}. Never any hidden reasoning - only what was suggested.
    llm_provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    edited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    draft: Mapped[ReportDraft] = relationship("ReportDraft", back_populates="qa_blocks")


class GeneratedReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An issued محضر. Immutable: a correction produces a NEW version, never an overwrite."""

    __tablename__ = "generated_reports"
    __table_args__ = (
        UniqueConstraint("session_id", "report_version", name="uq_generated_report_version"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The draft it was rendered from. SET NULL so deleting a draft never erases the record of
    # a document that was already submitted.
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("report_drafts.id", ondelete="SET NULL"), nullable=True
    )
    report_version: Mapped[int] = mapped_column(Integer, nullable=False)
    template_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("report_template_versions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Files under CENTRAL_STORAGE_ROOT: reports/{session_id}/...
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    context_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Integrity, not signature: three hashes let a submitted copy be checked later.
    docx_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    context_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    template_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Denormalized ON PURPOSE: what this exact document was built from, frozen. The draft may
    # move on; this row must still answer "which transcripts, which text mode, which
    # recordings" without depending on anything mutable.
    report_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    transcript_source_mode: Mapped[TranscriptSourceMode | None] = mapped_column(
        Enum(TranscriptSourceMode, name="transcript_source_mode"), nullable=True
    )
    selected_recording_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    pinned_transcripts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    qa_block_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
