"""subject identity and documents

Adds the person classification (military / civilian / unidentified), nationality,
Lebanese civil-registry identifiers and the `subject_documents` table holding
0..n identity documents per interviewed person, each with an optional scan.

Revision ID: d82371d11435
Revises: 8404f3cb8c30
Create Date: 2026-08-23 20:28:28.259406
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd82371d11435'
down_revision = '8404f3cb8c30'
branch_labels = None
depends_on = None

person_type = postgresql.ENUM("MILITARY", "CIVILIAN", "UNKNOWN", name="person_type", create_type=False)
security_branch = postgresql.ENUM(
    "ARMY", "ISF", "GENERAL_SECURITY", "STATE_SECURITY", "CUSTOMS", "OTHER", name="security_branch", create_type=False
)
undocumented_reason = postgresql.ENUM(
    "NO_DOCUMENTS", "REFUSED", "UNIDENTIFIED", "DOCUMENTS_WITHHELD", "OTHER", name="undocumented_reason", create_type=False
)
identity_confidence = postgresql.ENUM("DECLARED", "DOCUMENT_SEEN", "VERIFIED", name="identity_confidence", create_type=False)
subject_document_type = postgresql.ENUM(
    "NATIONAL_ID",
    "CIVIL_EXTRACT",
    "PASSPORT",
    "RESIDENCY_PERMIT",
    "UNHCR_CARD",
    "UNRWA_CARD",
    "REFUGEE_TRAVEL_DOC",
    "MILITARY_ID",
    "DRIVING_LICENSE",
    "OTHER",
    name="subject_document_type",
    create_type=False,
)
_ENUMS = (person_type, security_branch, undocumented_reason, identity_confidence, subject_document_type)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in _ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "subject_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("document_type", subject_document_type, nullable=False),
        sa.Column("document_number", sa.String(length=100), nullable=True),
        sa.Column("issuing_country", sa.String(length=100), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("storage_path", sa.String(length=500), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_subject_documents_document_number"), "subject_documents", ["document_number"], unique=False
    )
    op.create_index(op.f("ix_subject_documents_subject_id"), "subject_documents", ["subject_id"], unique=False)

    op.add_column("subjects", sa.Column("person_type", person_type, server_default="CIVILIAN", nullable=False))
    op.add_column("subjects", sa.Column("security_branch", security_branch, nullable=True))
    op.add_column("subjects", sa.Column("nationality_code", sa.String(length=2), nullable=True))
    op.add_column("subjects", sa.Column("nationality_name", sa.String(length=100), nullable=True))
    op.add_column("subjects", sa.Column("register_number", sa.String(length=64), nullable=True))
    op.add_column("subjects", sa.Column("place_of_registration", sa.String(length=200), nullable=True))
    op.add_column("subjects", sa.Column("is_unregistered", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("subjects", sa.Column("is_undocumented", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("subjects", sa.Column("undocumented_reason", undocumented_reason, nullable=True))
    op.add_column(
        "subjects",
        sa.Column("identity_confidence", identity_confidence, server_default="DECLARED", nullable=False),
    )

    # Existing rows that carry a military id are military subjects; the rest stay civilian.
    op.execute("UPDATE subjects SET person_type = 'MILITARY' WHERE military_id IS NOT NULL AND military_id <> ''")


def downgrade() -> None:
    for column in (
        "identity_confidence",
        "undocumented_reason",
        "is_undocumented",
        "is_unregistered",
        "place_of_registration",
        "register_number",
        "nationality_name",
        "nationality_code",
        "security_branch",
        "person_type",
    ):
        op.drop_column("subjects", column)
    op.drop_index(op.f("ix_subject_documents_subject_id"), table_name="subject_documents")
    op.drop_index(op.f("ix_subject_documents_document_number"), table_name="subject_documents")
    op.drop_table("subject_documents")
    bind = op.get_bind()
    for enum in _ENUMS:
        enum.drop(bind, checkfirst=True)
