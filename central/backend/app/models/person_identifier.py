"""External identifiers attached to a canonical person.

A canonical reference (CIV-*, MIL-*) is what the application calls someone. An external
identifier is what the WORLD calls them: a passport, an UNHCR card, a residency permit. They
serve different jobs, so they are different things:

  * the canonical reference is ours, permanent, and survives every document being reissued;
  * an external identifier is evidence that helps FIND an existing person, and may change,
    expire, or be corrected without the person becoming someone else.

Only an identifier whose namespace is PROVEN person-unique may resolve an identity
automatically. That is why `issuer_namespace` exists: a passport number means nothing without
the country that issued it, and a رقم سجل means nothing at all in this table - it identifies a
family record, so it stays on the Subject as searchable metadata and never resolves anyone.

Its only owner is person_identities.identity_id. This is not a second person registry.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PersonIdentifier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "person_identifiers"
    __table_args__ = (
        # The uniqueness that makes automatic resolution safe. Scoped by namespace because a
        # bare number is not an identity: passport 1234567 exists in many countries.
        UniqueConstraint(
            "identifier_type", "issuer_namespace", "value_normalized",
            name="uq_person_identifier_value",
        ),
    )

    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person_identities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # PASSPORT | RESIDENCY | UNHCR | UNRWA | LEBANESE_ID ...
    identifier_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # The authority the value is unique within. Empty string, never NULL: a NULL would make
    # the unique constraint stop applying, silently allowing duplicates for exactly the
    # agency-wide identifiers that need it most.
    issuer_namespace: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # As the operator entered it, for display and for the audit trail.
    value_display: Mapped[str] = mapped_column(String(100), nullable=False)
    # Folded by the same rule as canonical references, so MIL-٤٤٧١ and mil-4471 agree.
    value_normalized: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
