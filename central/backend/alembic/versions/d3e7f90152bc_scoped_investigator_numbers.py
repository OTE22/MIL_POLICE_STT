"""Service numbers are unique within their force, consistently with the person registry."""
from alembic import op
import sqlalchemy as sa
revision = "d3e7f90152bc"
down_revision = "c2d6e8f041ab"
branch_labels = None
depends_on = None

def upgrade():
    connection = op.get_bind()
    for constraint in sa.inspect(connection).get_unique_constraints("investigator_profiles"):
        if constraint["column_names"] == ["military_id"]:
            op.drop_constraint(constraint["name"], "investigator_profiles", type_="unique")
    op.create_unique_constraint("uq_investigator_service_number", "investigator_profiles", ["security_branch", "military_id"])

def downgrade():
    raise RuntimeError("Use a forward migration: cross-force serials may now coexist")
