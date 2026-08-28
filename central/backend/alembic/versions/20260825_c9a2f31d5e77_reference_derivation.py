"""Reference derivation: caza code, subject ids in, TMP sequence

الرقم المرجعي was the only identity field typed free-hand, so the same person arrived as
MIL-4471, MIL 4471 and 4471 - three canonical identities. Deriving it needs two things the
schema did not have: a validated محل القيد code (رقم السجل is unique within a قضاء, not
nationally) and a race-free allocator for people who carry no identifier at all.

Revision ID: c9a2f31d5e77
Revises: b7d4e91c02af
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "c9a2f31d5e77"
down_revision = "b7d4e91c02af"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subjects", sa.Column("caza_code", sa.String(length=32), nullable=True))

    # TMP-YYYY-NNNNNN. A sequence, never COUNT(*)+1 or MAX()+1: two investigators registering
    # undocumented people at the same moment must never receive the same reference. Never
    # reset per year - the year is display only, uniqueness is the guarantee.
    op.execute("CREATE SEQUENCE IF NOT EXISTS tmp_person_reference_seq START 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS tmp_person_reference_seq")
    op.drop_column("subjects", "caza_code")
