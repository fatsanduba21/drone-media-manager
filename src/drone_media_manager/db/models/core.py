"""Core local control-plane entities."""

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
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from drone_media_manager.db.base import Base
from drone_media_manager.domain.enums import JobStatus, WorkerStatus
from drone_media_manager.time import utc_now


class Worker(Base):
    """A registered worker that can lease and process jobs."""

    __tablename__ = "workers"
    __table_args__ = (
        CheckConstraint("status IN ('OFFLINE', 'ONLINE', 'BUSY')", name="ck_workers_status"),
        CheckConstraint("revision >= 0", name="ck_workers_revision_non_negative"),
        Index("ix_workers_status_last_seen_at", "status", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    token_digest: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=WorkerStatus.OFFLINE)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class Job(Base):
    """A durable unit of work, optionally leased to a worker."""

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'LEASED', 'RUNNING', 'COMPLETE', 'INTERRUPTED', 'FAILED')",
            name="ck_jobs_status",
        ),
        CheckConstraint("revision >= 0", name="ck_jobs_revision_non_negative"),
        CheckConstraint("attempts >= 0", name="ck_jobs_attempts_non_negative"),
        CheckConstraint("progress >= 0 AND progress <= 1", name="ck_jobs_progress_range"),
        Index("ix_jobs_status_available_at", "status", "available_at"),
        Index("ix_jobs_lease_expires_at", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    kind: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=JobStatus.PENDING)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    lease_worker_id: Mapped[str | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"), nullable=True
    )
    lease_token_digest: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class AuditEvent(Base):
    """Append-only record of an actor's result-bearing operation."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index(
            "ix_audit_events_entity_type_entity_id_occurred_at",
            "entity_type",
            "entity_id",
            "occurred_at",
        ),
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
