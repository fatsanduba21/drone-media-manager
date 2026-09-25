"""Versioned automated results and independent human decisions."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from drone_media_manager.db.base import Base
from drone_media_manager.time import utc_now


class MovementAnalysis(Base):
    __tablename__ = "movement_analyses"
    __table_args__ = (
        Index("ix_movement_analysis_asset", "catalog_asset_id", "superseded_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    catalog_asset_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_assets.id", ondelete="RESTRICT")
    )
    value: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    algorithm_version: Mapped[str] = mapped_column(String(32))
    parser_version: Mapped[str] = mapped_column(String(32))
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    evidence_json: Mapped[str] = mapped_column(Text)
    samples_json: Mapped[str] = mapped_column(Text)
    segments_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MovementReview(Base):
    __tablename__ = "movement_reviews"
    __table_args__ = (
        UniqueConstraint(
            "catalog_asset_id", "start_ms", "end_ms", name="uq_movement_review_interval"
        ),
        CheckConstraint(
            "(start_ms = -1 AND end_ms = -1) OR (start_ms >= 0 AND end_ms > start_ms)",
            name="ck_movement_review_interval",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    catalog_asset_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_assets.id", ondelete="RESTRICT")
    )
    start_ms: Mapped[int] = mapped_column(Integer, default=-1)
    end_ms: Mapped[int] = mapped_column(Integer, default=-1)
    value: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16), default="HUMAN")
    locked: Mapped[bool] = mapped_column(Boolean, default=True)
    actor: Mapped[str] = mapped_column(String(255))
    anchor_lat: Mapped[float | None] = mapped_column(Float)
    anchor_lon: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
