"""A speaker observation belongs to one recording, not to the whole session.

A diarizer's SPEAKER_00 is a cluster index local to ONE audio file. Keying speaker rows on
(session_id, speaker_label) made recording B's SPEAKER_00 resolve to recording A's row - so a
person confirmed in recording A was silently inherited by whoever spoke in recording B, and
the row's probe embedding was overwritten by each new voice (measured: a voice scoring 0.5372
against Ali - a different-person score - displayed as Ali).

This adds provenance: which recording the observation came from, and the label the diarizer
actually emitted there. Resolution becomes (session_id, recording_id, source_label), so
reprocessing the same recording reuses its rows while a different recording gets new ones.

Legacy rows keep recording_id NULL - their provenance was never recorded and is not invented.
The visible-label uniqueness (session_id, speaker_label) stays: labels remain session-unique.

Revision ID: f3d9c40a7e18
Revises: e5c8b19d4f27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "f3d9c40a7e18"
down_revision = "e5c8b19d4f27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("session_speakers", sa.Column("recording_id", UUID(as_uuid=True), nullable=True))
    op.add_column("session_speakers", sa.Column("source_label", sa.String(length=32), nullable=True))
    op.create_foreign_key(
        "fk_session_speakers_recording",
        "session_speakers",
        "audio_recordings",
        ["recording_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # The FK needs its own index (cascades scan the child side), and the partial unique index
    # is what makes reprocessing idempotent without constraining legacy NULL-provenance rows.
    op.create_index("ix_session_speakers_recording_id", "session_speakers", ["recording_id"])
    op.create_index(
        "uq_session_speaker_observation",
        "session_speakers",
        ["session_id", "recording_id", "source_label"],
        unique=True,
        postgresql_where=sa.text("recording_id IS NOT NULL"),
    )
    # Rows that exist today were resolved by their visible label; record that as the source
    # so a later reprocess of THE SAME recording does not duplicate them. recording_id stays
    # NULL - which recording produced them was never stored, and guessing would re-create the
    # exact class of error this migration removes.
    op.execute("UPDATE session_speakers SET source_label = speaker_label WHERE source_label IS NULL")


def downgrade() -> None:
    op.drop_index("uq_session_speaker_observation", table_name="session_speakers")
    op.drop_index("ix_session_speakers_recording_id", table_name="session_speakers")
    op.drop_constraint("fk_session_speakers_recording", "session_speakers", type_="foreignkey")
    op.drop_column("session_speakers", "source_label")
    op.drop_column("session_speakers", "recording_id")
