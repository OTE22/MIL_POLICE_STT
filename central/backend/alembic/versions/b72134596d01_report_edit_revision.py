"""Monotonic report revision prevents stale saves even after content changes back."""
from alembic import op
import sqlalchemy as sa

revision = "b72134596d01"
down_revision = "a61023485cef"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("report_drafts", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    raise RuntimeError("Use a forward migration for report concurrency changes")
