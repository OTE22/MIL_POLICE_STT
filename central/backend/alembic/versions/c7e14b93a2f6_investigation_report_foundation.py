"""The محضر تحقيق foundation: template versions, drafts, Q&A blocks, generated reports.

Four tables that keep the official investigation report a DERIVED document:

  report_template_versions  the organisation's one official layout, versioned
  report_drafts             one mutable working copy per session
  report_qa_blocks          the س/ج dialogue as it will be printed (source text COPIED,
                            never read through to transcript_segments at render time)
  generated_reports         issued documents: immutable, hashed, versioned

Nothing here touches existing tables. Evidence (recordings, transcripts, speakers,
identities, voice prints) is referenced, never rewritten - report editing changes the
report only, which is why the Q&A rows carry copies of their source text.

Revision ID: c7e14b93a2f6
Revises: a9f4e21c8b55
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

revision = "c7e14b93a2f6"
down_revision = "a9f4e21c8b55"
branch_labels = None
depends_on = None


# Two objects per enum on purpose: the types are CREATEd once explicitly (below), and the
# column definitions reference them with create_type=False. Letting a column create its own
# type breaks the moment two tables share one - transcript_source_mode is used by both
# report_drafts and generated_reports, and the second CREATE TYPE would abort the migration.
def _enum(*values: str, name: str) -> ENUM:
    return ENUM(*values, name=name, create_type=False)


ENUM_DEFS = {
    "report_status": ("DRAFT", "FINAL"),
    "transcript_source_mode": ("CORRECTED", "ORIGINAL"),
    "template_validation_status": ("UNVALIDATED", "VALID", "INVALID"),
    "fusha_status": ("NOT_REQUESTED", "AI_SUGGESTED", "HUMAN_EDITED", "APPROVED", "REJECTED"),
}

REPORT_STATUS = _enum(*ENUM_DEFS["report_status"], name="report_status")
SOURCE_MODE = _enum(*ENUM_DEFS["transcript_source_mode"], name="transcript_source_mode")
TEMPLATE_VALIDATION = _enum(*ENUM_DEFS["template_validation_status"], name="template_validation_status")
FUSHA_STATUS = _enum(*ENUM_DEFS["fusha_status"], name="fusha_status")


def upgrade() -> None:
    bind = op.get_bind()
    for name, values in ENUM_DEFS.items():
        ENUM(*values, name=name).create(bind, checkfirst=True)

    op.create_table(
        "report_template_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "validation_status",
            TEMPLATE_VALIDATION,
            nullable=False,
            server_default="UNVALIDATED",
        ),
        sa.Column("validation_message", sa.Text(), nullable=True),
        sa.Column("is_development", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("uploaded_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("version", name="uq_report_template_version"),
    )
    op.create_index("ix_report_template_versions_is_active", "report_template_versions", ["is_active"])

    op.create_table(
        "report_drafts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("investigation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", REPORT_STATUS, nullable=False, server_default="DRAFT"),
        sa.Column("report_number", sa.String(length=100), nullable=True),
        sa.Column("case_subject", sa.String(length=500), nullable=True),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column("report_time", sa.Time(), nullable=True),
        sa.Column("location", sa.String(length=300), nullable=True),
        sa.Column("intro_text", sa.Text(), nullable=True),
        sa.Column("closing_text", sa.Text(), nullable=True),
        sa.Column("transcript_source_mode", SOURCE_MODE, nullable=False, server_default="CORRECTED"),
        sa.Column("selected_recording_ids", JSONB(), nullable=True),
        sa.Column("pinned_transcripts", JSONB(), nullable=True),
        sa.Column("unresolved_ack", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("unresolved_ack_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("unresolved_ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", name="uq_report_draft_session"),
    )
    op.create_index("ix_report_drafts_session_id", "report_drafts", ["session_id"])

    op.create_table(
        "report_qa_blocks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "draft_id", UUID(as_uuid=True), sa.ForeignKey("report_drafts.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("question_source_text", sa.Text(), nullable=True),
        sa.Column("answer_source_text", sa.Text(), nullable=True),
        sa.Column("report_question_text", sa.Text(), nullable=True),
        sa.Column("report_answer_text", sa.Text(), nullable=True),
        sa.Column(
            "question_speaker_id",
            UUID(as_uuid=True),
            sa.ForeignKey("session_speakers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "answer_speaker_id",
            UUID(as_uuid=True),
            sa.ForeignKey("session_speakers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_segment_ids", JSONB(), nullable=True),
        sa.Column("source_recording_ids", JSONB(), nullable=True),
        sa.Column("start_seconds", sa.Float(), nullable=True),
        sa.Column("end_seconds", sa.Float(), nullable=True),
        sa.Column("included_in_report", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("exclusion_reason", sa.String(length=500), nullable=True),
        sa.Column("excluded_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fusha_status", FUSHA_STATUS, nullable=False, server_default="NOT_REQUESTED"),
        sa.Column("llm_suggested_question", sa.Text(), nullable=True),
        sa.Column("llm_suggested_answer", sa.Text(), nullable=True),
        sa.Column("llm_provenance", JSONB(), nullable=True),
        sa.Column("edited_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("draft_id", "sequence", name="uq_report_qa_sequence"),
    )
    op.create_index("ix_report_qa_blocks_draft_id", "report_qa_blocks", ["draft_id"])

    op.create_table(
        "generated_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("investigation_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL, not CASCADE: deleting a draft must never erase the record of a document
        # that was already issued and possibly submitted.
        sa.Column("draft_id", UUID(as_uuid=True), sa.ForeignKey("report_drafts.id", ondelete="SET NULL")),
        sa.Column("report_version", sa.Integer(), nullable=False),
        # RESTRICT: a template version referenced by an issued report cannot be deleted.
        sa.Column(
            "template_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("report_template_versions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("context_path", sa.String(length=500), nullable=True),
        sa.Column("docx_sha256", sa.String(length=64), nullable=False),
        sa.Column("context_sha256", sa.String(length=64), nullable=True),
        sa.Column("template_sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("report_number", sa.String(length=100), nullable=True),
        sa.Column("transcript_source_mode", SOURCE_MODE, nullable=True),
        sa.Column("selected_recording_ids", JSONB(), nullable=True),
        sa.Column("pinned_transcripts", JSONB(), nullable=True),
        sa.Column("qa_block_count", sa.Integer(), nullable=True),
        sa.Column("generated_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "report_version", name="uq_generated_report_version"),
    )
    op.create_index("ix_generated_reports_session_id", "generated_reports", ["session_id"])
    op.create_index("ix_generated_reports_template_version_id", "generated_reports", ["template_version_id"])
    op.create_index("ix_generated_reports_draft_id", "generated_reports", ["draft_id"])
    op.create_index("ix_report_drafts_created_by", "report_drafts", ["created_by"])


def downgrade() -> None:
    op.drop_table("generated_reports")
    op.drop_table("report_qa_blocks")
    op.drop_table("report_drafts")
    op.drop_table("report_template_versions")
    bind = op.get_bind()
    for name, values in ENUM_DEFS.items():
        ENUM(*values, name=name).drop(bind, checkfirst=True)
