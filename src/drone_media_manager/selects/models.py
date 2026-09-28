"""Separate automated suggestions from final human export decisions."""

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from drone_media_manager.db.base import Base
from drone_media_manager.time import utc_now


class SelectCandidate(Base):
    __tablename__ = "select_candidates"
    __table_args__ = (
        UniqueConstraint("catalog_asset_id", "proposed_start_ms", "proposed_end_ms"),
        CheckConstraint(
            "(proposed_start_ms = -1 AND proposed_end_ms = -1) OR (proposed_start_ms >= 0 AND proposed_end_ms > proposed_start_ms)",
            name="ck_select_candidate_proposed_interval",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'INCLUDE', 'REJECT')",
            name="ck_select_candidate_status",
        ),
        Index("ix_select_candidates_asset", "catalog_asset_id"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    catalog_asset_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_assets.id", ondelete="RESTRICT"), nullable=False
    )
    proposed_start_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    proposed_end_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    final_start_ms: Mapped[int | None] = mapped_column(Integer)
    final_end_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    movement: Mapped[str | None] = mapped_column(String(64))
    subject: Mapped[str | None] = mapped_column(String(255))
    people: Mapped[str | None] = mapped_column(String(32))
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
