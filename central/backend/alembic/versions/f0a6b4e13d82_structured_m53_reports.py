"""Structured M53 drafts and immutable PDF archives; existing Word reports preserved."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f0a6b4e13d82"
down_revision = "e9b5a3d02f71"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("report_drafts", sa.Column("official_form", postgresql.JSONB(), nullable=True))
    op.add_column("generated_reports", sa.Column("pdf_path", sa.String(500), nullable=True))
    op.add_column("generated_reports", sa.Column("pdf_sha256", sa.String(64), nullable=True))
    op.add_column("generated_reports", sa.Column("format_key", sa.String(30), nullable=True))


def downgrade():
    for name in ("format_key", "pdf_sha256", "pdf_path"):
        op.drop_column("generated_reports", name)
    op.drop_column("report_drafts", "official_form")
