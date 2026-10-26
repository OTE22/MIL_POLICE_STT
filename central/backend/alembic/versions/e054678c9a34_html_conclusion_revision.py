"""Permit the new structured conclusion template without changing historical archives."""
from alembic import op

revision = "e054678c9a34"
down_revision = "d943567b8f23"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_html_archive_format", "generated_reports", type_="check")
    op.create_check_constraint("ck_html_archive_format", "generated_reports",
                               "format_key IN ('statement-html-1', 'investigation-html-2')")


def downgrade():
    raise RuntimeError("Issued conclusion reports are immutable; use a forward repair.")
