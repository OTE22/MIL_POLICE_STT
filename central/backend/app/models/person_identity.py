"""Canonical person registry.

The one thing this table owns is identity: which real person a reference number belongs to.
It is deliberately tiny. `Subject` keeps recording a person's participation in a single
session; this row is what makes many such rows across many sessions converge on one person.

Merged rows are kept, not deleted. `merged_into_id` points at the survivor, and the retained
UNIQUE(reference_normalized) is what stops a stale client from recreating a reference that
was merged away.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PersonIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "person_identities"

    # The cross-session guarantee. Normalization rule lives in services/person_identity.py.
    reference_normalized: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    # The reference exactly as an investigator typed it, for display.
    reference_display: Mapped[str] = mapped_column(String(100), nullable=False)
    # Authoritative CURRENT name. Session-local and enrolment-time names are history.
    person_name: Mapped[str] = mapped_column(String(200), nullable=False)

    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person_identities.id", ondelete="SET NULL"), nullable=True, index=True
    )
