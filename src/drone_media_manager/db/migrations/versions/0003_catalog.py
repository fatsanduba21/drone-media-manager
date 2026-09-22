"""Add the independent editorial manifest catalog."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0003_catalog"
down_revision = "0002_ingest"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column[datetime], sa.Column[datetime]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def upgrade() -> None:
    op.create_table(
        "catalog_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "trip_id",
            sa.String(36),
            sa.ForeignKey("trips.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("codec", sa.String(128)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("fps", sa.Float()),
        sa.Column("encoded_width", sa.Integer()),
        sa.Column("encoded_height", sa.Integer()),
        sa.Column("display_width", sa.Integer()),
        sa.Column("display_height", sa.Integer()),
        sa.Column("rotation_degrees", sa.Float()),
        sa.Column("capture_date", sa.String(32)),
        sa.Column("capture_date_source", sa.String(64)),
        sa.Column("poi_final", sa.String(255)),
        sa.Column("poi_suggested", sa.String(255)),
        sa.Column("movement", sa.String(255)),
        sa.Column("people", sa.String(255)),
        sa.Column("verification_status", sa.String(32), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "media_type IN ('VIDEO', 'PHOTO')", name="ck_catalog_assets_media_type"
        ),
        sa.CheckConstraint(
            "classification IN ('YOUTUBE_16X9', 'INSTAGRAM_9X16', 'OUTROS_REVISAR', 'FOTOS')",
            name="ck_catalog_assets_classification",
        ),
    )
    op.create_index("ix_catalog_assets_trip_id", "catalog_assets", ["trip_id"])
    op.create_table(
        "asset_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "catalog_asset_id",
            sa.String(36),
            sa.ForeignKey("catalog_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("rel_path", sa.String(1024), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("availability_status", sa.String(32), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint(
            "catalog_asset_id", "role", name="uq_asset_files_asset_role"
        ),
        sa.CheckConstraint("role IN ('ORIGINAL', 'SRT')", name="ck_asset_files_role"),
        sa.CheckConstraint(
            "availability_status IN ('AVAILABLE', 'MISSING', 'UNVERIFIED', 'HASH_MISMATCH')",
            name="ck_asset_files_availability",
        ),
    )
    op.create_index("ix_asset_files_rel_path", "asset_files", ["rel_path"])
    op.create_table(
        "manifest_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "trip_id",
            sa.String(36),
            sa.ForeignKey("trips.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("manifest_rel_path", sa.String(1024), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("asset_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('IMPORTED', 'PARTIAL_AVAILABILITY')",
            name="ck_manifest_imports_status",
        ),
    )
    op.create_index(
        "ix_manifest_imports_trip_imported",
        "manifest_imports",
        ["trip_id", "imported_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_manifest_imports_trip_imported", table_name="manifest_imports")
    op.drop_table("manifest_imports")
    op.drop_index("ix_asset_files_rel_path", table_name="asset_files")
    op.drop_table("asset_files")
    op.drop_index("ix_catalog_assets_trip_id", table_name="catalog_assets")
    op.drop_table("catalog_assets")
