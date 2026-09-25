"""Profile weights; analysis snapshots live in existing persistent jobs."""

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from drone_media_manager.db.base import Base
from drone_media_manager.time import utc_now


class ScoringProfile(Base):
    __tablename__ = "scoring_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    weights_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
