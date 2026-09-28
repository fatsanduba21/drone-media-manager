"""Reviewable select candidates independent of scoring and original media."""

import sqlalchemy as sa
from alembic import op

revision = "0012_selects"
down_revision = "0011_scoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "select_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_asset_id",
            sa.String(36),
            sa.ForeignKey("catalog_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("proposed_start_ms", sa.Integer(), nullable=False),
        sa.Column("proposed_end_ms", sa.Integer(), nullable=False),
        sa.Column("final_start_ms", sa.Integer()),
        sa.Column("final_end_ms", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("suggested", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(128), nullable=False),
        sa.Column("score", sa.Float()),
        sa.Column("movement", sa.String(64)),
        sa.Column("subject", sa.String(255)),
        sa.Column("people", sa.String(32)),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("catalog_asset_id", "proposed_start_ms", "proposed_end_ms"),
        sa.CheckConstraint(
            "(proposed_start_ms = -1 AND proposed_end_ms = -1) OR (proposed_start_ms >= 0 AND proposed_end_ms > proposed_start_ms)",
            name="ck_select_candidate_proposed_interval",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'INCLUDE', 'REJECT')",
            name="ck_select_candidate_status",
        ),
    )
    op.create_index(
        "ix_select_candidates_asset", "select_candidates", ["catalog_asset_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_select_candidates_asset", table_name="select_candidates")
    op.drop_table("select_candidates")
