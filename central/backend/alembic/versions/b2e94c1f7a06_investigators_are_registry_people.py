"""Investigators are people in the canonical registry, not session staff.

An investigator speaks in the recordings they run, so they must be identifiable and
voice-enrollable exactly like anyone else. That means a row in `person_identities`, which
means a الرقم المرجعي, which means the force they belong to: a military serial is unique
*within its force*, so `MIL-<BRANCH>-<serial>` needs the branch or Army 4471 and ISF 4471
collide into one person - and one identity shared by two humans pools their voice prints.

`security_branch` is added NULLABLE because existing profiles predate the requirement and
cannot be guessed. New users are required to supply it (enforced in the schema), and an
existing investigator without it is refused at the moment they are assigned to a session,
with `investigator_profile_incomplete` naming what is missing. Guessing a branch here would
be inventing identity evidence.

Revision ID: b2e94c1f7a06
Revises: c4f70ab8d915
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID

revision = "b2e94c1f7a06"
down_revision = "c4f70ab8d915"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The enum already exists (subjects use it); reference it without trying to recreate.
    branch = postgresql.ENUM(name="security_branch", create_type=False)

    op.add_column("investigator_profiles", sa.Column("security_branch", branch, nullable=True))
    op.add_column(
        "investigator_profiles", sa.Column("reference_number", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "investigator_profiles",
        sa.Column("identity_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_investigator_profiles_identity",
        "investigator_profiles",
        "person_identities",
        ["identity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_investigator_profiles_identity_id", "investigator_profiles", ["identity_id"]
    )
    # Not unique: a reference is unique in person_identities, and that is the authority. Two
    # profile rows converging on one person is a merge to resolve, not a write to reject here.
    op.create_index(
        "ix_investigator_profiles_reference_number",
        "investigator_profiles",
        ["reference_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_investigator_profiles_reference_number", table_name="investigator_profiles")
    op.drop_index("ix_investigator_profiles_identity_id", table_name="investigator_profiles")
    op.drop_constraint(
        "fk_investigator_profiles_identity", "investigator_profiles", type_="foreignkey"
    )
    op.drop_column("investigator_profiles", "identity_id")
    op.drop_column("investigator_profiles", "reference_number")
    op.drop_column("investigator_profiles", "security_branch")
