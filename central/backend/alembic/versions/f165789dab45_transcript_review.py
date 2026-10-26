"""Bind explicit human transcript review to content and attribution without editing evidence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f165789dab45'
down_revision = 'e054678c9a34'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transcripts', sa.Column('review_token', sa.String(64), nullable=True))
    op.add_column('transcripts', sa.Column('reviewed_by', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('transcripts', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key('fk_transcript_reviewer', 'transcripts', 'users', ['reviewed_by'], ['id'], ondelete='SET NULL')


def downgrade():
    raise RuntimeError('Human review history must be preserved; use a forward repair.')
