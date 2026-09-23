"""Record generated media by catalog asset and kind."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_derivatives"
down_revision = "0003_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "derivatives",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_asset_id",
            sa.String(36),
            sa.ForeignKey("catalog_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("profile_version", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("rel_path", sa.String(1024)),
        sa.Column("output_sha256", sa.String(64)),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("error", sa.String(1024)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "catalog_asset_id", "kind", name="uq_derivatives_asset_kind"
        ),
        sa.CheckConstraint(
            "kind IN ('THUMBNAIL', 'PROXY')", name="ck_derivatives_kind"
        ),
        sa.CheckConstraint(
            "status IN ('READY', 'ERROR')", name="ck_derivatives_status"
        ),
    )
    op.create_index("ix_derivatives_status", "derivatives", ["status"])


def downgrade() -> None:
    op.drop_index("ix_derivatives_status", table_name="derivatives")
    op.drop_table("derivatives")
