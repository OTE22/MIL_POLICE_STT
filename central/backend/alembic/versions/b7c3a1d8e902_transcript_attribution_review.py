"""Audited attribution overlays preserve the original machine transcript."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7c3a1d8e902"
down_revision = "f0a6b4e13d82"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("transcript_segments", sa.Column("attribution_parts", postgresql.JSONB(), nullable=True))
    op.add_column("transcript_segments", sa.Column("attribution_reviewed_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("transcript_segments", sa.Column("attribution_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("transcript_segments", sa.Column("revision", sa.Integer(), server_default="0", nullable=False))
    op.create_foreign_key("fk_segment_attribution_reviewer", "transcript_segments", "users",
                          ["attribution_reviewed_by"], ["id"], ondelete="SET NULL")


def downgrade():
    op.drop_constraint("fk_segment_attribution_reviewer", "transcript_segments", type_="foreignkey")
    for name in ("revision", "attribution_reviewed_at", "attribution_reviewed_by", "attribution_parts"):
        op.drop_column("transcript_segments", name)
