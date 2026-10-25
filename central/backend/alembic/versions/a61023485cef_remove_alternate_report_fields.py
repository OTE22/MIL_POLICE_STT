"""HTML JSON is the sole editable report; QA rows are read-only import snapshots."""
from alembic import op

revision = "a61023485cef"
down_revision = "f50912374bde"
branch_labels = None
depends_on = None


def upgrade():
    for column in ("report_number", "case_subject", "report_date", "report_time", "location",
                   "intro_text", "closing_text", "unresolved_ack", "unresolved_ack_by", "unresolved_ack_at"):
        op.drop_column("report_drafts", column)
    for column in ("report_question_text", "report_answer_text", "included_in_report", "exclusion_reason",
                   "excluded_by", "excluded_at", "fusha_status", "llm_suggested_question", "llm_suggested_answer",
                   "llm_provenance", "edited_by", "edited_at"):
        op.drop_column("report_qa_blocks", column)
    op.execute("DROP TYPE IF EXISTS fusha_status")
    op.alter_column("generated_reports", "template_sha256", new_column_name="renderer_sha256")


def downgrade():
    raise RuntimeError("Use a forward repair or restore the pre-retirement backup")
