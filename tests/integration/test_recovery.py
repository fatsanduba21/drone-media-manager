"""Integration tests for restart recovery of expired jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from drone_media_manager.db.base import Base
from drone_media_manager.db.models.core import AuditEvent, Job, Worker
from drone_media_manager.domain.enums import JobStatus
from drone_media_manager.jobs.recovery import recover_on_startup


def test_restart_interrupts_expired_running_job_and_audits_recovery(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'recovery.sqlite3'}")
    Base.metadata.create_all(engine)
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)

    with Session(engine) as session, session.begin():
        session.add(Worker(id="worker-1", name="worker", token_digest="digest"))
        session.add(
            Job(
                id="job-1",
                kind="health-check",
                payload_json="{}",
                status=JobStatus.RUNNING,
                revision=2,
                attempts=1,
                available_at=now - timedelta(minutes=1),
                lease_worker_id="worker-1",
                lease_token_digest="lease-digest",
                lease_expires_at=now,
            )
        )

    report = recover_on_startup(lambda: Session(engine), now=now)

    with Session(engine) as session:
        job = session.get(Job, "job-1")
        events = session.scalars(select(AuditEvent)).all()

    assert report.interrupted_job_ids == ["job-1"]
    assert job is not None
    assert job.status == JobStatus.INTERRUPTED
    assert len(events) == 1
    assert events[0].action == "startup_recovery"
    assert events[0].entity_id == "job-1"
    assert events[0].result == "interrupted"
