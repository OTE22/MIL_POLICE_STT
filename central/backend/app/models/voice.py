"""Voice enrolment registry (biometric data - treat as highly sensitive).

An enrolment is a 256-dimension SpeakerNet-M embedding of a known person's voice,
created deliberately by an investigator from a speaker in a completed session. It is
used only to *suggest* a name for an anonymous speaker; the suggestion must be
confirmed by a human before it becomes the speaker's display name.

Consent and provenance are recorded with every enrolment so a transcript stays
auditable: which session the voice came from, who enrolled it, and under which model
and revision the embedding was produced (embeddings are not comparable across models).
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class VoiceEnrollment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "voice_enrollments"
    # A person may hold SEVERAL prints under one identity_id - different recording
    # conditions give better coverage, and the matcher groups them so they reinforce each
    # other rather than looking like two rival candidates. The index supports that
    # grouping; it is deliberately NOT unique.
    __table_args__ = (
        Index("ix_voice_enrollment_identity_model", "identity_id", "model"),
    )

    # ---- who ---------------------------------------------------------------
    # Canonical person UUID. Changes require an authorized identity-selection workflow.
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person_identities.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    person_name: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ---- the biometric template -------------------------------------------
    # pgvector, deliberately WITHOUT a fixed dimension: the contract accepts 16-1024 dims
    # (only the live SpeakerNet model is 256), and matching already filters candidates by
    # embedding_dim before any distance is computed. A typed vector(256) would reject every
    # other legitimate dimension. An ANN index would need a fixed-dim expression index -
    # exact search is used until measurement says otherwise.
    embedding: Mapped[list] = mapped_column(Vector(), nullable=False)
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    model_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sample_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ---- provenance and governance ----------------------------------------
    source_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("investigation_sessions.id", ondelete="SET NULL"), nullable=True
    )
    source_speaker_label: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consent_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    enrolled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
