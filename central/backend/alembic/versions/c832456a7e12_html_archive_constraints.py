"""Require complete HTML/PDF archives after authorized legacy retirement."""
from alembic import op

revision = "c832456a7e12"
down_revision = "b72134596d01"
branch_labels = None
depends_on = None


def upgrade():
    # Existing HTML archives must validate; an incomplete archive stops deployment
    # for explicit repair rather than deleting or silently rewriting its history.
    for column in ("format_key", "report_number", "html_path", "html_sha256", "pdf_path", "pdf_sha256",
                   "context_path", "context_sha256", "renderer_sha256", "size_bytes"):
        op.alter_column("generated_reports", column, nullable=False)
    op.create_check_constraint("ck_html_archive_format", "generated_reports", "format_key = 'statement-html-1'")
    op.create_check_constraint("ck_html_archive_version_size", "generated_reports", "report_version > 0 AND size_bytes > 0")
    op.create_check_constraint("ck_html_archive_hashes", "generated_reports",
        "html_sha256 ~ '^[0-9a-f]{64}$' AND pdf_sha256 ~ '^[0-9a-f]{64}$' "
        "AND context_sha256 ~ '^[0-9a-f]{64}$' AND renderer_sha256 ~ '^[0-9a-f]{64}$'")
    for table in ("report_drafts", "investigation_sessions", "transcript_segments"):
        op.create_check_constraint(f"ck_{table}_revision", table, "revision >= 0")


def downgrade():
    raise RuntimeError("Use a forward repair for HTML archive integrity constraints")
