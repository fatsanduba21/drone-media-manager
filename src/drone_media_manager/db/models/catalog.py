"""Editorial catalog entities for imported Phase 1 manifests."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from drone_media_manager.db.base import Base
from drone_media_manager.time import utc_now


def _uuid() -> str:
    return str(uuid4())


class CatalogAsset(Base):
    __tablename__ = "catalog_assets"
    __table_args__ = (
        CheckConstraint(
            "media_type IN ('VIDEO', 'PHOTO')", name="ck_catalog_assets_media_type"
        ),
        CheckConstraint(
            "classification IN ('YOUTUBE_16X9', 'INSTAGRAM_9X16', 'OUTROS_REVISAR', 'FOTOS')",
            name="ck_catalog_assets_classification",
        ),
        Index("ix_catalog_assets_trip_id", "trip_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    asset_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    trip_id: Mapped[str] = mapped_column(
        ForeignKey("trips.id", ondelete="RESTRICT"), nullable=False
    )
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    codec: Mapped[str | None] = mapped_column(String(128))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    encoded_width: Mapped[int | None] = mapped_column(Integer)
    encoded_height: Mapped[int | None] = mapped_column(Integer)
    display_width: Mapped[int | None] = mapped_column(Integer)
    display_height: Mapped[int | None] = mapped_column(Integer)
    rotation_degrees: Mapped[float | None] = mapped_column(Float)
    capture_date: Mapped[str | None] = mapped_column(String(32))
    capture_date_source: Mapped[str | None] = mapped_column(String(64))
    poi_final: Mapped[str | None] = mapped_column(String(255))
    poi_suggested: Mapped[str | None] = mapped_column(String(255))
    movement: Mapped[str | None] = mapped_column(String(255))
    people: Mapped[str | None] = mapped_column(String(255))
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class AssetFile(Base):
    __tablename__ = "asset_files"
    __table_args__ = (
        UniqueConstraint("catalog_asset_id", "role", name="uq_asset_files_asset_role"),
        CheckConstraint("role IN ('ORIGINAL', 'SRT')", name="ck_asset_files_role"),
        CheckConstraint(
            "availability_status IN ('AVAILABLE', 'MISSING', 'UNVERIFIED', 'HASH_MISMATCH')",
            name="ck_asset_files_availability",
        ),
        Index("ix_asset_files_rel_path", "rel_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    catalog_asset_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_assets.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    availability_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class ManifestImport(Base):
    __tablename__ = "manifest_imports"
    __table_args__ = (
        CheckConstraint(
            "status IN ('IMPORTED', 'PARTIAL_AVAILABILITY')",
            name="ck_manifest_imports_status",
        ),
        Index("ix_manifest_imports_trip_imported", "trip_id", "imported_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trip_id: Mapped[str] = mapped_column(
        ForeignKey("trips.id", ondelete="RESTRICT"), nullable=False
    )
    manifest_rel_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class Derivative(Base):
    """Latest generation attempt for one catalog asset and derivative kind."""

    __tablename__ = "derivatives"
    __table_args__ = (
        UniqueConstraint("catalog_asset_id", "kind", name="uq_derivatives_asset_kind"),
        CheckConstraint("kind IN ('THUMBNAIL', 'PROXY')", name="ck_derivatives_kind"),
        CheckConstraint("status IN ('READY', 'ERROR')", name="ck_derivatives_status"),
        Index("ix_derivatives_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    catalog_asset_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_assets.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rel_path: Mapped[str | None] = mapped_column(String(1024))
    output_sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(1024))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
