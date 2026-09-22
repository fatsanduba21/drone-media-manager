"""Create the SQLite safe-ingest persistence schema."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "0002_ingest"
down_revision = "0001_core"
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
    """Create source-relative ingest state with restrictive foreign keys."""

    op.create_table(
        "trips",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("nas_rel_path", sa.String(1024), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        sa.UniqueConstraint("nas_rel_path"),
    )
    op.create_table(
        "source_snapshots",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("worker_id", sa.String(36), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_volume_identity", sa.String(1024), nullable=True),
        sa.Column("source_fingerprint", sa.String(64), nullable=True),
        sa.Column("declared_item_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'FINALIZED', 'EXPIRED')",
            name="ck_source_snapshots_status",
        ),
        sa.CheckConstraint(
            "revision >= 0", name="ck_source_snapshots_revision_non_negative"
        ),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "source_snapshot_entries",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("source_rel_path", sa.String(1024), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("mtime_ns", sa.Integer(), nullable=False),
        sa.Column("file_identity", sa.String(1024), nullable=False),
        sa.Column("pair_status", sa.String(32), nullable=True),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["source_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id", "source_rel_path", name="uq_snapshot_entry_path"
        ),
    )
    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("source_snapshot_id", sa.String(36), nullable=True),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_volume_identity", sa.String(1024), nullable=True),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="DISCOVERED"),
        sa.Column("bytes_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bytes_verified", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('DISCOVERED', 'COPYING', 'VERIFYING', 'VERIFIED', 'INTERRUPTED', 'FAILED')",
            name="ck_ingest_jobs_status",
        ),
        sa.CheckConstraint(
            "revision >= 0", name="ck_ingest_jobs_revision_non_negative"
        ),
        sa.CheckConstraint(
            "bytes_total >= 0", name="ck_ingest_jobs_bytes_total_non_negative"
        ),
        sa.CheckConstraint(
            "bytes_verified >= 0", name="ck_ingest_jobs_bytes_verified_non_negative"
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_snapshot_id"], ["source_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "trip_id", "source_fingerprint", name="uq_ingest_trip_fingerprint"
        ),
    )
    op.create_table(
        "ingest_items",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("ingest_job_id", sa.String(36), nullable=False),
        sa.Column("source_rel_path", sa.String(1024), nullable=False),
        sa.Column("source_size_bytes", sa.Integer(), nullable=False),
        sa.Column("source_mtime_ns", sa.Integer(), nullable=False),
        sa.Column("source_file_identity", sa.String(1024), nullable=False),
        sa.Column("pair_status", sa.String(32), nullable=False),
        sa.Column("destination_rel_path", sa.String(1024), nullable=False),
        sa.Column("partial_rel_path", sa.String(1024), nullable=False),
        sa.Column("bytes_copied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_sha256", sa.String(64), nullable=True),
        sa.Column("destination_sha256", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('PENDING', 'COPYING', 'VERIFYING', 'VERIFIED', 'INTERRUPTED', 'FAILED')",
            name="ck_ingest_items_status",
        ),
        sa.CheckConstraint(
            "revision >= 0", name="ck_ingest_items_revision_non_negative"
        ),
        sa.CheckConstraint(
            "bytes_copied >= 0", name="ck_ingest_items_bytes_copied_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["ingest_job_id"], ["ingest_jobs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ingest_job_id", "source_rel_path", name="uq_ingest_item_source_path"
        ),
    )
    op.create_table(
        "media_files",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("ingest_item_id", sa.String(36), nullable=False),
        sa.Column("original_filename", sa.String(1024), nullable=False),
        sa.Column("rel_path", sa.String(1024), nullable=False),
        sa.Column("media_type", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["ingest_item_id"], ["ingest_items.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "trip_id",
            "media_type",
            "size_bytes",
            "sha256",
            name="uq_media_file_trip_identity",
        ),
    )
    op.create_table(
        "media_pairs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("trip_id", sa.String(36), nullable=False),
        sa.Column("video_media_id", sa.String(36), nullable=True),
        sa.Column("srt_media_id", sa.String(36), nullable=True),
        sa.Column("pair_status", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["video_media_id"], ["media_files.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["srt_media_id"], ["media_files.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "file_operations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("ingest_item_id", sa.String(36), nullable=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("source_rel_path", sa.String(1024), nullable=True),
        sa.Column("destination_rel_path", sa.String(1024), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["ingest_item_id"], ["ingest_items.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_snapshots_worker_status", "source_snapshots", ["worker_id", "status"]
    )
    op.create_index(
        "ix_ingest_jobs_status_created_at", "ingest_jobs", ["status", "created_at"]
    )
    op.create_index(
        "ix_ingest_items_ingest_status", "ingest_items", ["ingest_job_id", "status"]
    )
    op.create_index(
        "ix_file_operations_ingest_item_created_at",
        "file_operations",
        ["ingest_item_id", "created_at"],
    )


def downgrade() -> None:
    """Drop ingest state without affecting the Phase 0 control-plane schema."""

    op.drop_index(
        "ix_file_operations_ingest_item_created_at", table_name="file_operations"
    )
    op.drop_index("ix_ingest_items_ingest_status", table_name="ingest_items")
    op.drop_index("ix_ingest_jobs_status_created_at", table_name="ingest_jobs")
    op.drop_index("ix_source_snapshots_worker_status", table_name="source_snapshots")
    op.drop_table("file_operations")
    op.drop_table("media_pairs")
    op.drop_table("media_files")
    op.drop_table("ingest_items")
    op.drop_table("ingest_jobs")
    op.drop_table("source_snapshot_entries")
    op.drop_table("source_snapshots")
    op.drop_table("trips")
