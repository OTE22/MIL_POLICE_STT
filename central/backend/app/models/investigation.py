"""Investigation sessions, investigator assignments and interviewed subjects."""

from __future__ import annotations

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
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    AssignmentRole,
    IdentityConfidence,
    PersonType,
    SecurityBranch,
    SessionStatus,
    SubjectDocumentType,
    UndocumentedReason,
)


class InvestigationSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "investigation_sessions"

    session_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(300), nullable=True)
    session_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, name="session_status"), nullable=False, default=SessionStatus.DRAFT, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Operational warning input: the diarization model supports at most 4 speakers.
    expected_speaker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    investigators: Mapped[list[SessionInvestigator]] = relationship(
        "SessionInvestigator", back_populates="session", cascade="all, delete-orphan", lazy="selectin"
    )
    subjects: Mapped[list[Subject]] = relationship(
        "Subject", back_populates="session", cascade="all, delete-orphan", lazy="selectin"
    )
    recordings: Mapped[list["AudioRecording"]] = relationship(  # noqa: F821
        "AudioRecording", back_populates="session", cascade="all, delete-orphan"
    )
    speakers: Mapped[list["SessionSpeaker"]] = relationship(  # noqa: F821
        "SessionSpeaker", back_populates="session", cascade="all, delete-orphan"
    )
    transcripts: Mapped[list["Transcript"]] = relationship(  # noqa: F821
        "Transcript", back_populates="session", cascade="all, delete-orphan"
    )


class SessionInvestigator(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "session_investigators"
    __table_args__ = (UniqueConstraint("session_id", "investigator_id", name="uq_session_investigator"),)

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    investigator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigator_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    assignment_role: Mapped[AssignmentRole] = mapped_column(
        Enum(AssignmentRole, name="assignment_role"), nullable=False, default=AssignmentRole.ASSISTANT
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[InvestigationSession] = relationship("InvestigationSession", back_populates="investigators")
    investigator: Mapped["InvestigatorProfile"] = relationship("InvestigatorProfile", lazy="joined")  # noqa: F821


class Subject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subjects"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("investigation_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ---- identity classification -----------------------------------------
    person_type: Mapped[PersonType] = mapped_column(
        Enum(PersonType, name="person_type"), nullable=False, default=PersonType.CIVILIAN, server_default="CIVILIAN"
    )
    # Military subjects
    military_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rank: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    security_branch: Mapped[SecurityBranch | None] = mapped_column(
        Enum(SecurityBranch, name="security_branch"), nullable=True
    )
    # Civilian subjects
    nationality_code: Mapped[str | None] = mapped_column(String(2), nullable=True)  # ISO 3166-1 alpha-2
    nationality_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Lebanese civil-registry identity (رقم السجل + محل القيد are the authoritative identifiers)
    register_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    place_of_registration: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_unregistered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")  # مكتوم القيد
    # Undocumented / unidentified persons
    is_undocumented: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    undocumented_reason: Mapped[UndocumentedReason | None] = mapped_column(
        Enum(UndocumentedReason, name="undocumented_reason"), nullable=True
    )
    identity_confidence: Mapped[IdentityConfidence] = mapped_column(
        Enum(IdentityConfidence, name="identity_confidence"),
        nullable=False,
        default=IdentityConfidence.DECLARED,
        server_default="DECLARED",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped[InvestigationSession] = relationship("InvestigationSession", back_populates="subjects")
    documents: Mapped[list["SubjectDocument"]] = relationship(
        "SubjectDocument", back_populates="subject", cascade="all, delete-orphan", lazy="selectin"
    )


class SubjectDocument(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An identity document presented by a subject (0..n per person).

    The optional scan is stored on disk (never in the database); its SHA-256 is
    recorded and the file is treated as evidence: original never modified,
    access gated by the dedicated `subjects.documents.view` permission and audited.
    """

    __tablename__ = "subject_documents"

    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[SubjectDocumentType] = mapped_column(
        Enum(SubjectDocumentType, name="subject_document_type"), nullable=False
    )
    document_number: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    issuing_country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional scan (image/PDF) stored under CENTRAL_STORAGE_ROOT
    storage_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    subject: Mapped[Subject] = relationship("Subject", back_populates="documents")
