"""Allow several voice prints per person

A person may legitimately hold more than one voice print (different recording
conditions give better coverage). The previous UNIQUE (person_reference, model)
made that impossible, so operators worked around it by inventing a new reference
number for the same human - which then made the matcher treat one person as two
rival candidates and abstain on a perfect match.

Replaces the unique constraint with a plain index used for per-person grouping.

Revision ID: a3f1c7b9e204
Revises: f7fcea0351f9
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op

revision = "a3f1c7b9e204"
down_revision = "f7fcea0351f9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Which model produced a stored speaker embedding. Needed because embeddings are not
    # comparable across models and a re-scan must know this even for rows that never
    # produced a suggestion. Backfilled from suggested_model where one exists.
    op.add_column(
        "session_speakers", sa.Column("voice_embedding_model", sa.String(length=200), nullable=True)
    )
    op.execute(
        "UPDATE session_speakers SET voice_embedding_model = suggested_model "
        "WHERE voice_embedding IS NOT NULL AND suggested_model IS NOT NULL"
    )
    # Rows that never produced a suggestion have no suggested_model to copy. Only one
    # speaker-identification model has ever existed in this system (SpeakerNet-M, pinned
    # in desktop-agent/app/config.py, 256 dimensions), so a 256-d embedding can only have
    # come from it. The dimension guard keeps the assumption explicit and falsifiable.
    op.execute(
        "UPDATE session_speakers "
        "SET voice_embedding_model = 'nvidia/speakerverification_speakernet' "
        "WHERE voice_embedding IS NOT NULL AND voice_embedding_model IS NULL "
        "AND jsonb_array_length(voice_embedding) = 256"
    )
    op.drop_constraint("uq_voice_enrollment_person_model", "voice_enrollments", type_="unique")
    op.create_index(
        "ix_voice_enrollment_person_model",
        "voice_enrollments",
        ["person_reference", "model"],
        unique=False,
    )


def downgrade() -> None:
    # Deliberately strict: if a person has acquired several prints, this fails rather
    # than silently discarding biometric templates. Consolidate first, then downgrade.
    op.drop_index("ix_voice_enrollment_person_model", table_name="voice_enrollments")
    op.create_unique_constraint(
        "uq_voice_enrollment_person_model", "voice_enrollments", ["person_reference", "model"]
    )
    op.drop_column("session_speakers", "voice_embedding_model")
