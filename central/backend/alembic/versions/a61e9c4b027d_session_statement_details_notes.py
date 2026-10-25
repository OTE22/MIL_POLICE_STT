"""Session-specific statement facts and reusable, unfilled note wording."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a61e9c4b027d"
down_revision = "b7c3a1d8e902"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("subjects", sa.Column("statement_details", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.create_table("report_note_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("ix_report_note_templates_created_by", "report_note_templates", ["created_by"])


def downgrade():
    op.drop_table("report_note_templates")
    op.drop_column("subjects", "statement_details")
