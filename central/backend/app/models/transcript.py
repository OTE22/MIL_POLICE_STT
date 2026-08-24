"""Transcripts, transcript segments and speaker mappings."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import IdentificationStatus, SpeakerRole, TranscriptStatus


class Transcript(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "transcripts"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audio_recordings.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("local_processing_jobs.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    status: Mapped[TranscriptStatus] = mapped_column(
        Enum(TranscriptStatus, name="transcript_status"), nullable=False, default=TranscriptStatus.RECEIVED
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="ar")

    stt_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stt_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stt_model_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    diarization_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    diarization_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    diarization_model_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vad_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    processing_device: Mapped[str | None] = mapped_column(String(50), nullable=True)
    speaker_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    processing_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    session: Mapped["InvestigationSession"] = relationship(  # noqa: F821
        "InvestigationSession", back_populates="transcripts"
    )
    segments: Mapped[list[TranscriptSegment]] = relationship(
        "TranscriptSegment",
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.sequence",
        lazy="selectin",
    )


class TranscriptSegment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "transcript_segments"
    __table_args__ = (UniqueConstraint("transcript_id", "sequence", name="uq_segment_sequence"),)

    transcript_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker_label: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    start_seconds: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    end_seconds: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    # The AI result. Never overwritten.
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Human correction (nullable until edited).
    edited_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    is_overlap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    edited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    transcript: Mapped[Transcript] = relationship("Transcript", back_populates="segments")


class SessionSpeaker(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "session_speakers"
    __table_args__ = (UniqueConstraint("session_id", "speaker_label", name="uq_session_speaker_label"),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    speaker_label: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    speaker_role: Mapped[SpeakerRole] = mapped_column(
        Enum(SpeakerRole, name="speaker_role"), nullable=False, default=SpeakerRole.UNKNOWN
    )
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- voice-based identity SUGGESTION (never an assignment) -------------
    # display_name above is only ever written by a human. These fields record what the
    # voice comparison proposed, with the score and the model that produced it, so the
    # transcript stays auditable years later.
    identification_status: Mapped[IdentificationStatus] = mapped_column(
        Enum(IdentificationStatus, name="identification_status"),
        nullable=False,
        default=IdentificationStatus.NONE,
        server_default="NONE",
    )
    suggested_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    suggested_enrollment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("voice_enrollments.id", ondelete="SET NULL"), nullable=True
    )
    suggested_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    suggested_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    suggested_model_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    suggested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The speaker's own embedding, kept so a later enrolment can re-match this session
    # without reprocessing the audio.
    voice_embedding: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Which model produced `voice_embedding`. Embeddings are NOT comparable across
    # models, so a later re-scan must know this even when no suggestion was made.
    voice_embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)

    session: Mapped["InvestigationSession"] = relationship(  # noqa: F821
        "InvestigationSession", back_populates="speakers"
    )
