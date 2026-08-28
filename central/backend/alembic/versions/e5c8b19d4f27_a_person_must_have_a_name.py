"""A person must have a name, enforced by the database.

`subjects.subject_name` and `person_identities.person_name` were nullable, and
`get_or_create_identity` filled the gap with the reference itself. The result was a registry
row called "CIV-00000019": a placeholder that reads as data, is indistinguishable from a person
actually named that, and can never be found again.

The application now refuses a missing name. These constraints make it impossible regardless of
who is writing - a script, a migration, a future endpoint that forgets.

There is deliberately NO backfill. A row without a name has no name to recover, and inventing
one would put fabricated evidence in an investigation record. If this migration fails, the
offending rows are demo data: clear them with `scripts/reset_demo_data.sh --yes` and re-run.

Revision ID: e5c8b19d4f27
Revises: d1a7f30b6c94
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e5c8b19d4f27"
down_revision = "d1a7f30b6c94"
branch_labels = None
depends_on = None

# Fail with the count and a pointer, rather than a bare NOT NULL violation from Postgres.
_PRECHECK = """
DO $$
DECLARE bad_subjects bigint; bad_identities bigint;
BEGIN
  SELECT count(*) INTO bad_subjects FROM subjects
   WHERE subject_name IS NULL OR length(btrim(subject_name)) = 0;
  SELECT count(*) INTO bad_identities FROM person_identities
   WHERE person_name IS NULL OR length(btrim(person_name)) = 0;
  IF bad_subjects > 0 OR bad_identities > 0 THEN
    RAISE EXCEPTION
      'Cannot require a person name: % subject(s) and % identity(ies) have none. '
      'These cannot be backfilled - a missing name is not recoverable and must not be '
      'invented. Clear the demo data (scripts/reset_demo_data.sh --yes) and re-run.',
      bad_subjects, bad_identities;
  END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(_PRECHECK)

    op.alter_column("subjects", "subject_name", existing_type=sa.String(200), nullable=False)
    op.create_check_constraint(
        "ck_subjects_subject_name_not_blank", "subjects", "length(btrim(subject_name)) > 0"
    )

    op.alter_column(
        "person_identities", "person_name", existing_type=sa.String(200), nullable=False
    )
    op.create_check_constraint(
        "ck_person_identities_person_name_not_blank",
        "person_identities",
        "length(btrim(person_name)) > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_person_identities_person_name_not_blank", "person_identities")
    op.alter_column(
        "person_identities", "person_name", existing_type=sa.String(200), nullable=True
    )
    op.drop_constraint("ck_subjects_subject_name_not_blank", "subjects")
    op.alter_column("subjects", "subject_name", existing_type=sa.String(200), nullable=True)
