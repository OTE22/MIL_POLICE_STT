"""Session-local participation key for subjects.

`_apply_subjects` rebuilds the whole subject collection on every save: rows are deleted and
re-inserted, so `Subject.id` is destroyed and re-minted each time. That left the server with
no stable way to tell which submitted person is which existing participant, and TMP
allocation depended on the client echoing back an id that was already dead.

`participant_key` is that stable handle, and nothing more. It identifies a PARTICIPATION SLOT
within one session - never a person. It does not key `person_identities`, plays no part in
canonical identity matching, and never crosses a session boundary.

The unique constraint is DEFERRABLE on purpose: a rebuild deletes the old row and inserts the
new one carrying the SAME key inside one transaction, and SQLAlchemy's unit of work does not
guarantee the delete flushes first. An immediate constraint would fail a legitimate save.

Revision ID: e5c81a37bd94
Revises: c9a2f31d5e77
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5c81a37bd94"
down_revision = "c9a2f31d5e77"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subjects",
        sa.Column("participant_key", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Every existing participant gets one, so the column can be NOT NULL and reconciliation
    # never has to cope with a keyless row.
    op.execute("UPDATE subjects SET participant_key = gen_random_uuid() WHERE participant_key IS NULL")
    op.alter_column("subjects", "participant_key", nullable=False)
    op.create_index("ix_subjects_participant_key", "subjects", ["participant_key"])
    op.create_unique_constraint(
        "uq_subject_participant_key",
        "subjects",
        ["session_id", "participant_key"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint("uq_subject_participant_key", "subjects", type_="unique")
    op.drop_index("ix_subjects_participant_key", table_name="subjects")
    op.drop_column("subjects", "participant_key")
