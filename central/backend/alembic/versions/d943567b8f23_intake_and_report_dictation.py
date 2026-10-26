"""Intake exception provenance and separately purposed report dictation."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d943567b8f23"
down_revision = "c832456a7e12"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("subjects", sa.Column("field_exceptions", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("audio_recordings", sa.Column("purpose", sa.String(30), nullable=False, server_default="INTERVIEW"))
    op.add_column("audio_recordings", sa.Column("report_context", postgresql.JSONB(), nullable=True))
    op.create_check_constraint("ck_recording_purpose", "audio_recordings", "purpose IN ('INTERVIEW', 'REPORT_DICTATION')")


def downgrade():
    raise RuntimeError("Report dictation provenance is retained; use a forward repair.")
