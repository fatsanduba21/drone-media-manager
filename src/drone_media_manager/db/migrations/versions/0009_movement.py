"""Add independent movement suggestions and human reviews; no media changes."""

import sqlalchemy as sa
from alembic import op

revision = "0009_movement"
down_revision = "0008_capture_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "movement_analyses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_asset_id",
            sa.String(36),
            sa.ForeignKey("catalog_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("value", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("parser_version", sa.String(32), nullable=False),
        sa.Column("source_sha256", sa.String(64)),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("samples_json", sa.Text(), nullable=False),
        sa.Column("segments_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_movement_analysis_asset",
        "movement_analyses",
        ["catalog_asset_id", "superseded_at"],
    )
    op.create_table(
        "movement_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_asset_id",
            sa.String(36),
            sa.ForeignKey("catalog_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(64)),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("anchor_lat", sa.Float()),
        sa.Column("anchor_lon", sa.Float()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "catalog_asset_id", "start_ms", "end_ms", name="uq_movement_review_interval"
        ),
        sa.CheckConstraint(
            "(start_ms = -1 AND end_ms = -1) OR (start_ms >= 0 AND end_ms > start_ms)",
            name="ck_movement_review_interval",
        ),
    )


def downgrade() -> None:
    op.drop_table("movement_reviews")
    op.drop_table("movement_analyses")
