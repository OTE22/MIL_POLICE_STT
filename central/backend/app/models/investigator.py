"""Investigator profile (HR-style data kept separate from the login identity)."""

from __future__ import annotations

import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import SecurityBranch


class InvestigatorProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "investigator_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    rank: Mapped[str | None] = mapped_column(String(100), nullable=True)
    military_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    # The force the serial belongs to. Part of the reference key, because a serial is unique
    # only WITHIN its force - without it, Army 4471 and ISF 4471 become one person.
    security_branch: Mapped[SecurityBranch | None] = mapped_column(
        SAEnum(SecurityBranch, name="security_branch"), nullable=True
    )
    unit: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department: Mapped[str | None] = mapped_column(String(200), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # An investigator speaks in the sessions they run, so they are a person like any other:
    # identifiable, and eligible for a voice print. Filled when they are assigned to a session.
    identity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person_identities.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    user: Mapped["User"] = relationship("User", back_populates="profile", foreign_keys=[user_id])  # noqa: F821
