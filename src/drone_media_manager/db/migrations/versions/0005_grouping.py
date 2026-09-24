"""Add Phase 3A telemetry, suggestions and confirmed location groups."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_grouping"
down_revision = "0004_derivatives"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "location_groups",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "trip_id",
            sa.String(36),
            sa.ForeignKey("trips.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name_final", sa.String(255), nullable=False),
        sa.Column("name_source", sa.String(32), nullable=False),
        sa.Column("name_locked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_location_groups_trip_id", "location_groups", ["trip_id"])
    op.execute(
        "ALTER TABLE catalog_assets ADD COLUMN location_group_id "
        "VARCHAR(36) REFERENCES location_groups(id) ON DELETE SET NULL"
    )
    op.create_index(
        "ix_catalog_assets_location_group_id",
        "catalog_assets",
        ["location_group_id"],
    )
    op.create_table(
        "telemetry_tracks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_asset_id",
            sa.String(36),
            sa.ForeignKey("catalog_assets.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("parser_version", sa.String(32), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True)),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("start_lat", sa.Float()),
        sa.Column("start_lon", sa.Float()),
        sa.Column("end_lat", sa.Float()),
        sa.Column("end_lon", sa.Float()),
        sa.Column("centroid_lat", sa.Float()),
        sa.Column("centroid_lon", sa.Float()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "grouping_suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "trip_id",
            sa.String(36),
            sa.ForeignKey("trips.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "start_asset_id",
            sa.String(36),
            sa.ForeignKey("catalog_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "end_asset_id",
            sa.String(36),
            sa.ForeignKey("catalog_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("algorithm_version", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_grouping_suggestions_trip_id", "grouping_suggestions", ["trip_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_grouping_suggestions_trip_id", table_name="grouping_suggestions")
    op.drop_table("grouping_suggestions")
    op.drop_table("telemetry_tracks")
    op.drop_index("ix_catalog_assets_location_group_id", table_name="catalog_assets")
    op.execute("ALTER TABLE catalog_assets DROP COLUMN location_group_id")
    op.drop_index("ix_location_groups_trip_id", table_name="location_groups")
    op.drop_table("location_groups")
