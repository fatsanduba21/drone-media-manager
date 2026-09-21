"""Control-plane restart recovery for expired leased work."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from drone_media_manager.db.models.core import AuditEvent, Job
from drone_media_manager.jobs.repository import JobRepository


@dataclass(frozen=True)
class RecoveryReport:
    interrupted_job_ids: list[str] = field(default_factory=list)
    audit_event_ids: list[str] = field(default_factory=list)


def recover_on_startup(
    session_factory: Callable[[], Session], now: datetime
) -> RecoveryReport:
    correlation_id = str(uuid4())
    audit_event_ids = []

    def audit(session: Session, job: Job) -> None:
        event_id = str(uuid4())
        audit_event_ids.append(event_id)
        session.add(
            AuditEvent(
                id=event_id,
                actor="system",
                action="startup_recovery",
                entity_type="job",
                entity_id=job.id,
                result="interrupted",
                details_json=json.dumps({}, separators=(",", ":")),
                correlation_id=correlation_id,
                occurred_at=now,
            )
        )

    with session_factory() as session:
        interrupted_job_ids = JobRepository(
            session, on_mutation=audit
        ).interrupt_expired(now)
    return RecoveryReport(
        interrupted_job_ids=interrupted_job_ids, audit_event_ids=audit_event_ids
    )
