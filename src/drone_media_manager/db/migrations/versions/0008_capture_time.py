"""Store capture time for chronological editorial review."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_capture_time"
down_revision = "0007_location_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("catalog_assets", sa.Column("capture_time", sa.String(40)))
    # Old suggestion endpoints refer to the previous file order; confirmed
    # group memberships are independent and remain untouched.
    op.execute(
        "UPDATE grouping_suggestions SET superseded_at = CURRENT_TIMESTAMP "
        "WHERE superseded_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("catalog_assets", "capture_time")
