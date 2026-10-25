"""محضر تحقيق: the official investigation report — HTML draft, source import cache, immutable archive.

Three tables, one purpose each, and the boundaries between them are the point:

  HTML report JSON owns editable content; renderer assets own presentation.
  report_drafts             the INVESTIGATOR's working copy for one session. Mutable.
  report_qa_blocks          derived source import snapshots. Rebuilt only by explicit refresh.
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

from sqlalchemy import (
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
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

    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Versioned structured form values; confirmation events are written by the
    # authenticated server and bound to an exact content digest.
    official_form: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

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
    # Files under CENTRAL_STORAGE_ROOT: reports/{session_id}/...
    html_path: Mapped[str] = mapped_column(String(500), nullable=False)
    html_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    context_path: Mapped[str] = mapped_column(String(500), nullable=False)
    pdf_path: Mapped[str] = mapped_column(String(500), nullable=False)
    pdf_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    format_key: Mapped[str] = mapped_column(String(30), nullable=False)
    # Integrity, not signature: three hashes let a submitted copy be checked later.
    context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    renderer_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Denormalized ON PURPOSE: what this exact document was built from, frozen. The draft may
    # move on; this row must still answer "which transcripts, which text mode, which
    # recordings" without depending on anything mutable.
    report_number: Mapped[str] = mapped_column(String(100), nullable=False)
    transcript_source_mode: Mapped[TranscriptSourceMode | None] = mapped_column(
        Enum(TranscriptSourceMode, name="transcript_source_mode"), nullable=True
    )
    selected_recording_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    pinned_transcripts: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    qa_block_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
