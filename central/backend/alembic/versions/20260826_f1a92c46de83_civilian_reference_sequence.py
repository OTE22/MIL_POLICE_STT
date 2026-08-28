"""System-generated civilian canonical references (CIV-*).

رقم السجل identifies a FAMILY civil record, not one human: an إخراج قيد lists everyone
registered under it. Deriving LBN-<CAZA>-<REGISTER> therefore keyed relatives to one canonical
person - blocking the second relative outright when their names differed, and silently merging
them when they did not (naming a son after his grandfather is ordinary here). Merging two
humans into one biometric identity is not recoverable; an extra identity awaiting consolidation
is.

So civilians stop deriving from civil-register data and receive a system-generated reference
instead. The sequence is the allocator - never COUNT(*)+1 or MAX()+1, which race - and it is
globally monotonic and never reset, because uniqueness matters more than tidy numbering.

Revision ID: f1a92c46de83
Revises: e5c81a37bd94
"""

from __future__ import annotations

from alembic import op

revision = "f1a92c46de83"
down_revision = "e5c81a37bd94"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS civilian_person_reference_seq START 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS civilian_person_reference_seq")
