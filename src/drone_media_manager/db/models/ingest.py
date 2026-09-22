"""Persistent safe-ingest entities owned by the Mac control plane."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from drone_media_manager.db.base import Base
from drone_media_manager.domain.enums import IngestItemStatus, IngestStatus
from drone_media_manager.time import utc_now


def _uuid() -> str:
    return str(uuid4())


class Trip(Base):
    """A server-owned logical destination for imported media."""

    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    nas_rel_path: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SourceSnapshot(Base):
    """A worker-authenticated, relative-path-only inventory draft."""

    __tablename__ = "source_snapshots"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'FINALIZED', 'EXPIRED')",
            name="ck_source_snapshots_status",
        ),
        CheckConstraint(
            "revision >= 0", name="ck_source_snapshots_revision_non_negative"
        ),
        Index("ix_source_snapshots_worker_status", "worker_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("workers.id", ondelete="RESTRICT")
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_volume_identity: Mapped[str | None] = mapped_column(String(1024))
    source_fingerprint: Mapped[str | None] = mapped_column(String(64))
    declared_item_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SourceSnapshotEntry(Base):
    """One immutable source-relative record uploaded with a snapshot."""

    __tablename__ = "source_snapshot_entries"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "source_rel_path", name="uq_snapshot_entry_path"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="RESTRICT")
    )
    source_rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mtime_ns: Mapped[int] = mapped_column(Integer, nullable=False)
    file_identity: Mapped[str] = mapped_column(String(1024), nullable=False)
    pair_status: Mapped[str | None] = mapped_column(String(32))


class IngestJob(Base):
    """Aggregate lifecycle and idempotency identity for one confirmed ingest."""

    __tablename__ = "ingest_jobs"
    __table_args__ = (
        UniqueConstraint(
            "trip_id", "source_fingerprint", name="uq_ingest_trip_fingerprint"
        ),
        CheckConstraint(
            "status IN ('DISCOVERED', 'COPYING', 'VERIFYING', 'VERIFIED', 'INTERRUPTED', 'FAILED')",
            name="ck_ingest_jobs_status",
        ),
        CheckConstraint("revision >= 0", name="ck_ingest_jobs_revision_non_negative"),
        CheckConstraint(
            "bytes_total >= 0", name="ck_ingest_jobs_bytes_total_non_negative"
        ),
        CheckConstraint(
            "bytes_verified >= 0", name="ck_ingest_jobs_bytes_verified_non_negative"
        ),
        Index("ix_ingest_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="RESTRICT"))
    source_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_snapshots.id", ondelete="RESTRICT")
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_volume_identity: Mapped[str | None] = mapped_column(String(1024))
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=IngestStatus.DISCOVERED)
    bytes_total: Mapped[int] = mapped_column(Integer, default=0)
    bytes_verified: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class IngestItem(Base):
    """Per-file progress, hashes, and durable relative destination state."""

    __tablename__ = "ingest_items"
    __table_args__ = (
        UniqueConstraint(
            "ingest_job_id", "source_rel_path", name="uq_ingest_item_source_path"
        ),
        CheckConstraint(
            "status IN ('PENDING', 'COPYING', 'VERIFYING', 'VERIFIED', 'INTERRUPTED', 'FAILED')",
            name="ck_ingest_items_status",
        ),
        CheckConstraint("revision >= 0", name="ck_ingest_items_revision_non_negative"),
        CheckConstraint(
            "bytes_copied >= 0", name="ck_ingest_items_bytes_copied_non_negative"
        ),
        Index("ix_ingest_items_ingest_status", "ingest_job_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ingest_job_id: Mapped[str] = mapped_column(
        ForeignKey("ingest_jobs.id", ondelete="RESTRICT")
    )
    source_rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_mtime_ns: Mapped[int] = mapped_column(Integer, nullable=False)
    source_file_identity: Mapped[str] = mapped_column(String(1024), nullable=False)
    pair_status: Mapped[str] = mapped_column(String(32), nullable=False)
    destination_rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    partial_rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    bytes_copied: Mapped[int] = mapped_column(Integer, default=0)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    destination_sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default=IngestItemStatus.PENDING)
    error: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MediaFile(Base):
    """A verified media identity, deduplicated within its trip."""

    __tablename__ = "media_files"
    __table_args__ = (
        UniqueConstraint(
            "trip_id",
            "media_type",
            "size_bytes",
            "sha256",
            name="uq_media_file_trip_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="RESTRICT"))
    ingest_item_id: Mapped[str] = mapped_column(
        ForeignKey("ingest_items.id", ondelete="RESTRICT")
    )
    original_filename: Mapped[str] = mapped_column(String(1024), nullable=False)
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class MediaPair(Base):
    """A catalog-level relationship retaining optional-SRT state."""

    __tablename__ = "media_pairs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(ForeignKey("trips.id", ondelete="RESTRICT"))
    video_media_id: Mapped[str | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="RESTRICT")
    )
    srt_media_id: Mapped[str | None] = mapped_column(
        ForeignKey("media_files.id", ondelete="RESTRICT")
    )
    pair_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )


class FileOperation(Base):
    """Append-only operational record using logical paths only."""

    __tablename__ = "file_operations"
    __table_args__ = (
        Index(
            "ix_file_operations_ingest_item_created_at", "ingest_item_id", "created_at"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    ingest_item_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingest_items.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    source_rel_path: Mapped[str | None] = mapped_column(String(1024))
    destination_rel_path: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
