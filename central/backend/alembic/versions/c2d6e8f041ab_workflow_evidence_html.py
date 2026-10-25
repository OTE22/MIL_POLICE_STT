"""Stable evidence records and independent investigation lifecycle; HTML artifacts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "c2d6e8f041ab"
down_revision = "a61e9c4b027d"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("investigation_sessions", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("investigation_sessions", sa.Column("workflow_state", sa.String(32), nullable=False, server_default="DRAFT"))
    op.execute("UPDATE investigation_sessions SET workflow_state=CASE WHEN status::text='ARCHIVED' THEN 'ARCHIVED' WHEN status::text='DRAFT' THEN 'DRAFT' ELSE 'IN_PROGRESS' END")
    op.create_check_constraint("ck_workflow_state", "investigation_sessions", "workflow_state IN ('DRAFT','IN_PROGRESS','AWAITING_REVIEW','REVIEWED','CLOSED','ARCHIVED')")
    op.add_column("subjects", sa.Column("removed_at", sa.DateTime(timezone=True)))
    op.add_column("subject_documents", sa.Column("removed_at", sa.DateTime(timezone=True)))
    op.add_column("subject_documents", sa.Column("file_versions", JSONB(), nullable=False, server_default="[]"))
    op.add_column("generated_reports", sa.Column("html_path", sa.String(500)))
    op.add_column("generated_reports", sa.Column("html_sha256", sa.String(64)))
    op.alter_column("generated_reports", "storage_path", nullable=True)
    op.alter_column("generated_reports", "docx_sha256", nullable=True)
    # NOT VALID avoids rejecting historical rows; new writes are checked immediately.
    op.execute("ALTER TABLE transcript_segments ADD CONSTRAINT ck_segment_time CHECK (start_seconds>=0 AND end_seconds>=start_seconds) NOT VALID")
    op.execute("ALTER TABLE transcript_segments ADD CONSTRAINT ck_segment_confidence CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1) NOT VALID")


def downgrade():
    raise RuntimeError("Evidence-preserving migration: restore a backup or use a forward migration")
