"""Audio recordings, workstation registry and local processing jobs."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import JobStatus, RecordingSource, RecordingUploadStatus, WorkstationStatus


class AudioRecording(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "audio_recordings"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[RecordingSource] = mapped_column(Enum(RecordingSource, name="recording_source"), nullable=False)
    upload_status: Mapped[RecordingUploadStatus] = mapped_column(
        Enum(RecordingUploadStatus, name="recording_upload_status"),
        nullable=False,
        default=RecordingUploadStatus.PENDING,
    )
    # Relative to CENTRAL_STORAGE_ROOT, e.g. recordings/{session_uuid}/{recording_uuid}.wav
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    session: Mapped["InvestigationSession"] = relationship(  # noqa: F821
        "InvestigationSession", back_populates="recordings"
    )


class Workstation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workstations"

    agent_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    device_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    stt_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stt_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    stt_model_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    diarization_provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    diarization_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    diarization_model_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    processing_device: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gpu_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[WorkstationStatus] = mapped_column(
        Enum(WorkstationStatus, name="workstation_status"), nullable=False, default=WorkstationStatus.ONLINE
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class LocalProcessingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "local_processing_jobs"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recording_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audio_recordings.id", ondelete="CASCADE"), nullable=False
    )
    workstation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workstations.id", ondelete="SET NULL"), nullable=True
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"), nullable=False, default=JobStatus.REQUESTED, index=True
    )
    # Mirror of the Local Agent state machine (CREATED ... COMPLETED / FAILED / CANCELLED)
    agent_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    token_nonce: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    token_issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_accept_by: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    failure_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    recording: Mapped[AudioRecording] = relationship("AudioRecording", lazy="joined")
    workstation: Mapped[Workstation | None] = relationship("Workstation", lazy="joined")
