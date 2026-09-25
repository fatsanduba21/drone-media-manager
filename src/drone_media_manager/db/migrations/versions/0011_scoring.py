"""Editable score profiles; historical results use durable job snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0011_scoring"
down_revision = "0010_editorial_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scoring_profiles",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("weights_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("scoring_profiles")
