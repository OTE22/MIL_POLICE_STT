"""The voice gallery moves to pgvector so matching is one SQL operation.

`voice_enrollments.embedding` was jsonb, so every match loaded the whole gallery into Python
and computed cosine there. With pgvector the database computes `1 - (embedding <=> probe)`
for all probes of a recording against all eligible prints in a single statement.

The column becomes a DIMENSION-LESS `vector`, not `vector(256)`: the API contract accepts
16-1024 dimensions (only the live SpeakerNet model is 256), matching already filters
candidates by `embedding_dim` before any distance is computed, and a typed column would
reject every other legitimate dimension. jsonb's text form `[0.1, 0.2]` is valid vector
input, so the conversion is a cast.

`session_speakers.voice_embedding` stays jsonb: it is a probe and an enrolment source,
never searched.

REQUIRES the pgvector extension - the postgres image must be pgvector/pgvector:pg16 (the
compose file was changed with this revision). On an image without the extension this
migration fails at CREATE EXTENSION, which is the correct failure.

Revision ID: a9f4e21c8b55
Revises: f3d9c40a7e18
"""

from __future__ import annotations

from alembic import op

revision = "a9f4e21c8b55"
down_revision = "f3d9c40a7e18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "ALTER TABLE voice_enrollments "
        "ALTER COLUMN embedding TYPE vector USING (embedding::text)::vector"
    )


def downgrade() -> None:
    # vector's text form '[0.1,0.2]' is valid json, so the reverse is also a cast.
    op.execute(
        "ALTER TABLE voice_enrollments "
        "ALTER COLUMN embedding TYPE jsonb USING (embedding::text)::jsonb"
    )
    # The extension is left installed: another database in the cluster may use it, and
    # DROP EXTENSION would fail anyway if anything still depends on it.
