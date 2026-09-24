"""Join Phase 2D authentication and Phase 3A grouping migration histories.

Both 0005 revisions have independent schemas. Alembic applies the missing
branch before reaching this revision, preserving databases migrated on either
feature branch.
"""

from __future__ import annotations

revision = "0006_merge_2d_3a"
down_revision = ("0005_gallery_auth", "0005_grouping")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
