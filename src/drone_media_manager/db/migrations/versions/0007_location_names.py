"""Keep an allowed provider identifier for a confirmed location name."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_location_names"
down_revision = "0006_merge_2d_3a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("location_groups", sa.Column("provider_place_id", sa.Text()))


def downgrade() -> None:
    op.drop_column("location_groups", "provider_place_id")
