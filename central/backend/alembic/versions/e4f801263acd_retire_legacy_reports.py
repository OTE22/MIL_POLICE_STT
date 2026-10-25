"""Retire Word/M53 records; retain only the canonical HTML reporting workflow.

Deletion of legacy reports, drafts and templates was explicitly authorized by the owner.
Investigation evidence and audit history are deliberately outside this migration.
"""
from alembic import op

revision = "e4f801263acd"
down_revision = "d3e7f90152bc"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM generated_reports WHERE format_key IS DISTINCT FROM 'statement-html-1'")
    op.execute("DELETE FROM report_drafts WHERE jsonb_typeof(official_form->'html_report') IS DISTINCT FROM 'object'")
    op.drop_column("generated_reports", "template_version_id")
    op.drop_column("generated_reports", "storage_path")
    op.drop_column("generated_reports", "docx_sha256")
    op.drop_table("report_template_versions")
    op.execute("DROP TYPE IF EXISTS template_validation_status")


def downgrade():
    raise RuntimeError("Legacy retirement is irreversible; use a forward repair or the pre-deployment backup")
