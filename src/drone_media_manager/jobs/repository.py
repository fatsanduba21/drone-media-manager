"""Short SQLite transactions for durable job ownership.

Each operation owns and completes its transaction. Pass an idle Session; a
caller's pending transaction is never committed or rolled back implicitly.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable, Iterator
from collections.abc import Set as AbstractSet
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from drone_media_manager.db.models.core import Job, Worker
from drone_media_manager.domain.enums import JobStatus
from drone_media_manager.domain.errors import LeaseConflict
from drone_media_manager.jobs.transitions import assert_job_transition
from drone_media_manager.time import utc_now

MutationHook = Callable[[Session, Job], None]


@dataclass(frozen=True)
class ClaimedJob:
    """Detached snapshot. Only claim returns the secret, excluded from repr."""

    id: str
    kind: str
    payload_json: str
    status: JobStatus
    revision: int
    attempts: int
    progress: float
    lease_worker_id: str | None
    lease_expires_at: datetime | None
    lease_token: str | None = field(default=None, repr=False)


def _utc(value: datetime) -> datetime:
    # SQLite DateTime loads stored UTC values without their timezone.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _snapshot(job: Job, token: str | None = None) -> ClaimedJob:
    return ClaimedJob(
        id=job.id,
        kind=job.kind,
        payload_json=job.payload_json,
        status=JobStatus(job.status),
        revision=job.revision,
        attempts=job.attempts,
        progress=job.progress,
        lease_worker_id=job.lease_worker_id,
        lease_expires_at=_utc(job.lease_expires_at) if job.lease_expires_at else None,
        lease_token=token,
    )


class JobRepository:
    """Own transactions while allowing related writes through ``on_mutation``.

    The optional hook receives the same session and the mutated job, once per
    changed job, before commit. It may add an audit row or update a worker;
    it must not commit, roll back, or perform external I/O. Any hook or flush
    failure rolls back all writes in the operation. Empty claims, rejected
    requests and empty expiry sweeps do not invoke the hook.
    """

    def __init__(
        self, session: Session, *, clock: Callable[[], datetime] = utc_now,
        on_mutation: MutationHook | None = None,
    ) -> None:
        self.session = session
        self.clock = clock
        self.on_mutation = on_mutation

    def _before_commit(self, job: Job) -> None:
        if self.on_mutation is not None:
            self.on_mutation(self.session, job)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if self.session.in_transaction():
            raise RuntimeError("JobRepository requires an idle session")
        with self.session.begin():
            self.session.execute(text("BEGIN IMMEDIATE"))
            yield

    def claim(
        self, worker_id: str, capabilities: AbstractSet[str], lease_seconds: int
    ) -> ClaimedJob | None:
        """Atomically lease the oldest available compatible pending job."""
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if not capabilities:
            return None
        with self._transaction():
            now = _utc(self.clock())
            if self.session.get(Worker, worker_id) is None:
                raise LeaseConflict("Unknown worker")
            job = self.session.scalar(
                select(Job)
                .where(
                    Job.status == JobStatus.PENDING,
                    Job.kind.in_(capabilities),
                    Job.available_at <= now,
                )
                .order_by(Job.created_at, Job.id)
                .limit(1)
                .execution_options(populate_existing=True)
            )
            if job is None:
                return None
            token = secrets.token_hex(32)
            assert_job_transition(JobStatus(job.status), JobStatus.LEASED)
            job.status = JobStatus.LEASED
            job.lease_worker_id = worker_id
            job.lease_token_digest = hashlib.sha256(token.encode()).hexdigest()
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            job.revision += 1
            job.attempts += 1
            job.updated_at = now
            self._before_commit(job)
            result = _snapshot(job, token)
        return result

    def _owned_job(
        self, job_id: str, worker_id: str, token: str, revision: int, now: datetime
    ) -> Job:
        job = self.session.get(Job, job_id, populate_existing=True)
        if (
            job is None
            or job.status not in (JobStatus.LEASED, JobStatus.RUNNING)
            or job.lease_worker_id != worker_id
            or job.revision != revision
            or job.lease_expires_at is None
            or _utc(job.lease_expires_at) <= now
            or job.lease_token_digest is None
            or not hmac.compare_digest(job.lease_token_digest, hashlib.sha256(token.encode()).hexdigest())
        ):
            raise LeaseConflict("Lease ownership, revision or expiry does not match")
        return job

    def renew(
        self, job_id: str, worker_id: str, lease_token: str,
        expected_revision: int, lease_seconds: int,
    ) -> ClaimedJob:
        """Extend a live lease and advance its revision, without reissuing its token."""
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        with self._transaction():
            now = _utc(self.clock())
            job = self._owned_job(job_id, worker_id, lease_token, expected_revision, now)
            assert job.lease_expires_at is not None  # Checked by _owned_job.
            job.lease_expires_at = max(_utc(job.lease_expires_at), now + timedelta(seconds=lease_seconds))
            job.revision += 1
            job.updated_at = now
            self._before_commit(job)
            result = _snapshot(job)
        return result

    def progress(
        self, job_id: str, worker_id: str, lease_token: str,
        expected_revision: int, progress: float,
    ) -> ClaimedJob:
        """Checkpoint progress, entering RUNNING on the first live report."""
        if not 0 <= progress <= 1:
            raise ValueError("progress must be between zero and one")
        with self._transaction():
            now = _utc(self.clock())
            job = self._owned_job(job_id, worker_id, lease_token, expected_revision, now)
            if job.status != JobStatus.RUNNING:
                assert_job_transition(JobStatus(job.status), JobStatus.RUNNING)
                job.status = JobStatus.RUNNING
            job.progress = progress
            job.revision += 1
            job.updated_at = now
            self._before_commit(job)
            result = _snapshot(job)
        return result

    def interrupt_expired(self, now: datetime) -> list[str]:
        """Invalidate expired ownership, preserving checkpoints for reconciliation."""
        now = _utc(now)
        with self._transaction():
            jobs = self.session.scalars(
                select(Job)
                .where(
                    Job.status.in_((JobStatus.LEASED, JobStatus.RUNNING)),
                    Job.lease_expires_at <= now,
                )
                .order_by(Job.id)
                .execution_options(populate_existing=True)
            ).all()
            for job in jobs:
                assert_job_transition(JobStatus(job.status), JobStatus.INTERRUPTED)
                job.status = JobStatus.INTERRUPTED
                job.revision += 1
                job.updated_at = now
                job.lease_worker_id = None
                job.lease_token_digest = None
                job.lease_expires_at = None
                self._before_commit(job)
            ids = [job.id for job in jobs]
        return ids

    def complete(
        self, job_id: str, worker_id: str, lease_token: str, expected_revision: int,
    ) -> ClaimedJob:
        """Finish a running job only while its lease is current."""
        return self._finish(job_id, worker_id, lease_token, expected_revision, JobStatus.COMPLETE, None)

    def fail(
        self, job_id: str, worker_id: str, lease_token: str, expected_revision: int, error: str,
    ) -> ClaimedJob:
        """Fail a live job. The API must supply a sanitized, non-secret error."""
        return self._finish(job_id, worker_id, lease_token, expected_revision, JobStatus.FAILED, error)

    def _finish(
        self, job_id: str, worker_id: str, lease_token: str, expected_revision: int,
        target: JobStatus, error: str | None,
    ) -> ClaimedJob:
        with self._transaction():
            now = _utc(self.clock())
            job = self._owned_job(job_id, worker_id, lease_token, expected_revision, now)
            assert_job_transition(JobStatus(job.status), target)
            job.status = target
            job.error = error
            if target == JobStatus.COMPLETE:
                job.progress = 1.0
            job.revision += 1
            job.updated_at = now
            job.lease_worker_id = None
            job.lease_token_digest = None
            job.lease_expires_at = None
            self._before_commit(job)
            result = _snapshot(job)
        return result

    def reconcile(self, job_id: str, expected_revision: int) -> ClaimedJob:
        """Explicit control-plane action after external recovery checks succeed.

        File reconciliation is the caller's responsibility. This operation only
        makes an interrupted job eligible again, preserving its checkpoint.
        """
        with self._transaction():
            job = self.session.get(Job, job_id, populate_existing=True)
            if job is None or job.revision != expected_revision:
                raise LeaseConflict("Reconciliation revision does not match")
            assert_job_transition(JobStatus(job.status), JobStatus.PENDING)
            job.status = JobStatus.PENDING
            job.revision += 1
            job.updated_at = _utc(self.clock())
            self._before_commit(job)
            result = _snapshot(job)
        return result
