"""Stable person UUIDs shared by sessions, investigators and voiceprints.

Merged rows remain as UUID aliases so stale selections resolve to the surviving person.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PersonIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "person_identities"

    # Authoritative CURRENT name. Session-local and enrolment-time names are history.
    person_name: Mapped[str] = mapped_column(String(200), nullable=False)

    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person_identities.id", ondelete="SET NULL"), nullable=True, index=True
    )
