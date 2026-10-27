"""Allow the opening-enabled HTML archive format; retain every historical format."""
from alembic import op

revision = "a27689aebc56"
down_revision = "f165789dab45"
branch_labels = None
depends_on = None


def upgrade():
    # PostgreSQL transactional DDL: existing archive rows remain untouched.
    op.drop_constraint("ck_html_archive_format", "generated_reports", type_="check")
    op.create_check_constraint("ck_html_archive_format", "generated_reports",
                               "format_key IN ('statement-html-1', 'investigation-html-2', 'investigation-html-3')")


def downgrade():
    raise RuntimeError("Issued v3 archives must remain readable; use a forward repair.")
