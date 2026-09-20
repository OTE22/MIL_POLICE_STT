"""Persist source voice provenance independently of matching suggestions.

Unknown historical provenance remains unknown; never infer it from today's model.
"""
from alembic import op
import sqlalchemy as sa

revision = "e9b5a3d02f71"
down_revision = "d8a4f2c91e60"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("session_speakers", sa.Column("voice_embedding_revision", sa.String(100)))
    op.add_column("session_speakers", sa.Column("voice_embedding_provider", sa.String(100)))
    op.add_column("session_speakers", sa.Column("voice_embedding_seconds", sa.Numeric(12, 3)))
    op.execute("""UPDATE session_speakers SET voice_embedding_revision = suggested_model_revision
                  WHERE voice_embedding_model = suggested_model""")
    # Pending suggestions must be recomputed under the stricter compatibility rules.
    op.execute("""UPDATE session_speakers SET identification_status='NONE',
                  suggested_enrollment_id=NULL, suggested_name=NULL, suggested_score=NULL,
                  suggested_model=NULL, suggested_model_revision=NULL, suggested_at=NULL
                  WHERE identification_status='SUGGESTED'""")


def downgrade():
    for column in ("voice_embedding_seconds", "voice_embedding_provider", "voice_embedding_revision"):
        op.drop_column("session_speakers", column)
