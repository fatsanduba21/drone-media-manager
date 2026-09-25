"""Confirmed editorial fields and tags live beside imported catalog data."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from drone_media_manager.db.base import Base
from drone_media_manager.time import utc_now


class EditorialField(Base):
    __tablename__ = "editorial_fields"
    __table_args__ = (UniqueConstraint("catalog_asset_id", "kind"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    catalog_asset_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_assets.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="HUMAN")
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class EditorialTag(Base):
    __tablename__ = "editorial_tags"
    __table_args__ = (UniqueConstraint("catalog_asset_id", "value"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    catalog_asset_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_assets.id", ondelete="RESTRICT"), nullable=False
    )
    value: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="HUMAN")
    confidence: Mapped[float | None] = mapped_column(Float)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
