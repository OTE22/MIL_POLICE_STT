"""External identifiers attached to a canonical person.

Separates what the application calls someone (CIV-*, MIL-*) from what the world calls them
(passport, UNHCR card, residency permit). The canonical reference is permanent; documents are
reissued, corrected and replaced without the person becoming someone else.

The unique constraint is scoped by issuer namespace on purpose: passport 1234567 exists in
many countries, so a bare number is not an identity. رقم السجل is deliberately absent from this
table - it identifies a family record, not a human, and stays on the Subject as searchable
metadata that never resolves anyone.

Revision ID: a7d3e0c9b512
Revises: f1a92c46de83
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7d3e0c9b512"
down_revision = "f1a92c46de83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "person_identifiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identifier_type", sa.String(length=32), nullable=False),
        # Empty string, never NULL: a NULL would switch the unique constraint off for exactly
        # the agency-wide identifiers that most need it.
        sa.Column("issuer_namespace", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("value_display", sa.String(length=100), nullable=False),
        sa.Column("value_normalized", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["identity_id"], ["person_identities.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "identifier_type", "issuer_namespace", "value_normalized",
            name="uq_person_identifier_value",
        ),
    )
    op.create_index("ix_person_identifiers_identity_id", "person_identifiers", ["identity_id"])
    op.create_index("ix_person_identifiers_value_normalized", "person_identifiers", ["value_normalized"])


def downgrade() -> None:
    op.drop_index("ix_person_identifiers_value_normalized", table_name="person_identifiers")
    op.drop_index("ix_person_identifiers_identity_id", table_name="person_identifiers")
    op.drop_table("person_identifiers")
