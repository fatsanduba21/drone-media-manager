"""Repository behavior on migrated SQLite, including independent concurrent sessions."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.core import Job, Worker
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.domain.enums import JobStatus
from drone_media_manager.domain.errors import LeaseConflict
from drone_media_manager.jobs.repository import ClaimedJob, JobRepository

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    settings = ServerSettings(
        database_path=tmp_path / "leases.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["server_settings"] = settings
    command.upgrade(config, "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        session.add_all(
            Worker(id=f"worker-{n}", name=f"worker-{n}", token_digest=f"digest-{n}")
            for n in range(2)
        )
    yield sessions
    engine.dispose()


def seed(factory: sessionmaker[Session], **fields: object) -> str:
    values: dict[str, object] = {
        "id": "job-1", "kind": "ingest", "payload_json": '{"source":"card"}',
        "status": JobStatus.PENDING, "available_at": NOW, "created_at": NOW,
    }
    values.update(fields)
    with factory.begin() as session:
        job = Job(**values)
        session.add(job)
    return job.id


def snapshot(factory: sessionmaker[Session], job_id: str = "job-1") -> dict[str, object]:
    with factory() as session:
        job = session.get(Job, job_id)
        assert job is not None
        return {column.name: getattr(job, column.name) for column in Job.__table__.columns}


def claim(factory: sessionmaker[Session]) -> ClaimedJob:
    with factory() as session:
        result = JobRepository(session, clock=lambda: NOW).claim("worker-0", {"ingest"}, 30)
    assert result is not None
    return result


def test_claim_persists_lease_and_only_a_digest(factory: sessionmaker[Session]) -> None:
    seed(factory)
    result = claim(factory)
    row = snapshot(factory)
    assert result.id == "job-1"
    assert result.status == JobStatus.LEASED
    assert result.revision == 1
    assert result.attempts == 1
    assert result.payload_json == '{"source":"card"}'
    assert result.lease_expires_at == NOW + timedelta(seconds=30)
    assert len(bytes.fromhex(result.lease_token)) == 32
    assert row["status"] == JobStatus.LEASED
    assert row["lease_worker_id"] == "worker-0"
    assert row["lease_token_digest"] == hashlib.sha256(result.lease_token.encode()).hexdigest()
    assert result.lease_token not in str(row)


def test_claim_oldest_eligible_job_only(factory: sessionmaker[Session]) -> None:
    seed(factory, id="wrong-kind", kind="analyze", created_at=NOW - timedelta(days=4))
    seed(factory, id="future", available_at=NOW + timedelta(seconds=1), created_at=NOW - timedelta(days=3))
    seed(factory, id="newer")
    seed(factory, id="oldest", created_at=NOW - timedelta(days=1))
    assert claim(factory).id == "oldest"


def test_two_concurrent_sessions_cannot_claim_same_job(factory: sessionmaker[Session]) -> None:
    seed(factory)
    barrier = Barrier(2)

    def compete(worker: str) -> ClaimedJob | None:
        with factory() as session:
            barrier.wait(timeout=5)
            return JobRepository(session, clock=lambda: NOW).claim(worker, {"ingest"}, 30)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(compete, ["worker-0", "worker-1"]))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert snapshot(factory)["attempts"] == 1
    assert snapshot(factory)["revision"] == 1


def test_no_capabilities_claims_nothing(factory: sessionmaker[Session]) -> None:
    seed(factory)
    with factory() as session:
        assert JobRepository(session, clock=lambda: NOW).claim("worker-0", set(), 30) is None
        assert not session.in_transaction()
    assert snapshot(factory)["revision"] == 0


def test_unknown_worker_does_not_mutate_job(factory: sessionmaker[Session]) -> None:
    seed(factory)
    before = snapshot(factory)
    with factory() as session, pytest.raises(LeaseConflict):
        JobRepository(session, clock=lambda: NOW).claim("missing", {"ingest"}, 30)
    assert snapshot(factory) == before


@pytest.mark.parametrize("seconds", [0, -1])
def test_claim_rejects_nonpositive_duration(factory: sessionmaker[Session], seconds: int) -> None:
    seed(factory)
    with factory() as session, pytest.raises(ValueError):
        JobRepository(session, clock=lambda: NOW).claim("worker-0", {"ingest"}, seconds)
    assert snapshot(factory)["revision"] == 0


def test_claim_releases_lock_before_return(factory: sessionmaker[Session]) -> None:
    seed(factory)
    seed(factory, id="job-2")
    with factory() as first, factory() as second:
        assert JobRepository(first, clock=lambda: NOW).claim("worker-0", {"ingest"}, 30)
        assert not first.in_transaction()
        assert JobRepository(second, clock=lambda: NOW).claim("worker-1", {"ingest"}, 30)
        assert not second.in_transaction()
    with factory() as session:
        assert len(session.scalars(select(Job).where(Job.status == JobStatus.LEASED)).all()) == 2


def test_renew_extends_lease_and_fences_old_revision(factory: sessionmaker[Session]) -> None:
    seed(factory)
    initial = claim(factory)
    with factory() as session:
        renewed = JobRepository(session, clock=lambda: NOW + timedelta(seconds=10)).renew(
            initial.id, "worker-0", initial.lease_token, 1, 60
        )
        assert not session.in_transaction()
    assert renewed.revision == 2
    assert renewed.lease_expires_at == NOW + timedelta(seconds=70)
    assert renewed.attempts == 1
    assert renewed.status == JobStatus.LEASED
    assert renewed.lease_token is None
    with factory() as session, pytest.raises(LeaseConflict):
        JobRepository(session, clock=lambda: NOW + timedelta(seconds=11)).renew(
            initial.id, "worker-0", initial.lease_token, 1, 60
        )
    assert snapshot(factory)["revision"] == 2


@pytest.mark.parametrize("operation", ["renew", "progress"])
@pytest.mark.parametrize("invalid", ["worker", "token", "revision", "expired", "missing"])
def test_lease_mutations_reject_stale_or_unauthorized_requests_without_writes(
    factory: sessionmaker[Session], operation: str, invalid: str
) -> None:
    seed(factory)
    initial = claim(factory)
    before = snapshot(factory)
    worker = "worker-1" if invalid == "worker" else "worker-0"
    token = "wrong" if invalid == "token" else initial.lease_token
    revision = 0 if invalid == "revision" else 1
    now = NOW + timedelta(seconds=30 if invalid == "expired" else 1)
    job_id = "missing" if invalid == "missing" else initial.id
    with factory() as session:
        repository = JobRepository(session, clock=lambda: now)
        with pytest.raises(LeaseConflict):
            if operation == "renew":
                repository.renew(job_id, worker, token, revision, 30)
            else:
                repository.progress(job_id, worker, token, revision, 0.5)
        assert not session.in_transaction()
    assert snapshot(factory) == before


def test_progress_starts_running_and_persists_checkpoints(factory: sessionmaker[Session]) -> None:
    seed(factory)
    initial = claim(factory)
    with factory() as session:
        repository = JobRepository(session, clock=lambda: NOW + timedelta(seconds=1))
        first = repository.progress(initial.id, "worker-0", initial.lease_token, 1, 0.25)
        second = repository.progress(initial.id, "worker-0", initial.lease_token, 2, 0.75)
    assert first.status == JobStatus.RUNNING
    assert second.revision == 3
    assert second.progress == 0.75
    assert second.lease_token is None
    assert snapshot(factory)["progress"] == 0.75
    assert second.lease_expires_at == initial.lease_expires_at


@pytest.mark.parametrize("progress", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_progress_does_not_consume_revision(factory: sessionmaker[Session], progress: float) -> None:
    seed(factory)
    initial = claim(factory)
    before = snapshot(factory)
    with factory() as session, pytest.raises(ValueError):
        JobRepository(session, clock=lambda: NOW).progress(initial.id, "worker-0", initial.lease_token, 1, progress)
    assert snapshot(factory) == before


@pytest.mark.parametrize("running", [False, True])
def test_expiry_interrupts_and_requires_explicit_reconciliation(
    factory: sessionmaker[Session], running: bool
) -> None:
    seed(factory)
    initial = claim(factory)
    with factory() as session:
        repository = JobRepository(session, clock=lambda: NOW)
        if running:
            repository.progress(initial.id, "worker-0", initial.lease_token, 1, 0.5)
        assert repository.interrupt_expired(NOW + timedelta(seconds=29)) == []
        assert repository.interrupt_expired(NOW + timedelta(seconds=30)) == [initial.id]
        assert repository.interrupt_expired(NOW + timedelta(seconds=31)) == []
    interrupted = snapshot(factory)
    assert interrupted["status"] == JobStatus.INTERRUPTED
    assert interrupted["revision"] == (3 if running else 2)
    assert interrupted["lease_worker_id"] is None
    assert interrupted["lease_token_digest"] is None
    assert interrupted["lease_expires_at"] is None
    assert interrupted["progress"] == (0.5 if running else 0)
    with factory() as session:
        repository = JobRepository(session, clock=lambda: NOW + timedelta(seconds=31))
        assert repository.claim("worker-1", {"ingest"}, 30) is None
        reconciled = repository.reconcile(initial.id, interrupted["revision"])
        assert reconciled.status == JobStatus.PENDING
        assert reconciled.revision == interrupted["revision"] + 1
        retried = repository.claim("worker-1", {"ingest"}, 30)
        assert retried is not None
        assert retried.attempts == 2
        assert retried.lease_token != initial.lease_token
        with pytest.raises(LeaseConflict):
            repository.progress(initial.id, "worker-0", initial.lease_token, retried.revision, 1)


def test_concurrent_renewal_allows_only_one_revision_winner(factory: sessionmaker[Session]) -> None:
    seed(factory)
    initial = claim(factory)
    barrier = Barrier(2)

    def renew(_: int) -> bool:
        with factory() as session:
            repository = JobRepository(session, clock=lambda: NOW + timedelta(seconds=1))
            barrier.wait(timeout=5)
            try:
                repository.renew(initial.id, "worker-0", initial.lease_token, 1, 30)
                return True
            except LeaseConflict:
                return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(renew, range(2))) == [False, True]
    assert snapshot(factory)["revision"] == 2


def test_reconcile_rejects_stale_revision(factory: sessionmaker[Session]) -> None:
    seed(factory, status=JobStatus.INTERRUPTED, revision=3)
    before = snapshot(factory)
    with factory() as session, pytest.raises(LeaseConflict):
        JobRepository(session, clock=lambda: NOW).reconcile("job-1", 2)
    assert snapshot(factory) == before


def test_reconcile_cannot_reset_running_job(factory: sessionmaker[Session]) -> None:
    from drone_media_manager.domain.errors import InvalidTransition

    seed(factory, status=JobStatus.RUNNING, revision=3)
    before = snapshot(factory)
    with factory() as session, pytest.raises(InvalidTransition):
        JobRepository(session, clock=lambda: NOW).reconcile("job-1", 3)
    assert snapshot(factory) == before


def test_claim_rolls_back_all_lease_fields_on_database_failure(factory: sessionmaker[Session]) -> None:
    seed(factory)
    before = snapshot(factory)
    with factory.begin() as session:
        session.execute(text("CREATE TRIGGER reject_claim BEFORE UPDATE ON jobs BEGIN SELECT RAISE(ABORT, 'write rejected'); END"))
    with factory() as session:
        with pytest.raises(IntegrityError, match="write rejected"):
            JobRepository(session, clock=lambda: NOW).claim("worker-0", {"ingest"}, 30)
        assert not session.in_transaction()
    assert snapshot(factory) == before


def test_repository_does_not_commit_or_rollback_callers_transaction(factory: sessionmaker[Session]) -> None:
    seed(factory)
    with factory() as session:
        job = session.get(Job, "job-1")
        job.payload_json = '{"uncommitted":true}'
        with pytest.raises(RuntimeError, match="idle session"):
            JobRepository(session, clock=lambda: NOW).claim("worker-0", {"ingest"}, 30)
        assert session.in_transaction()
        assert job in session.dirty
    assert snapshot(factory)["payload_json"] == '{"source":"card"}'


def test_cached_job_cannot_bypass_revision_fence(factory: sessionmaker[Session]) -> None:
    seed(factory)
    initial = claim(factory)
    with factory() as stale:
        cached = stale.get(Job, initial.id)
        stale.commit()
        with factory() as fresh:
            JobRepository(fresh, clock=lambda: NOW).renew(initial.id, "worker-0", initial.lease_token, 1, 60)
        assert cached.revision == 1
        with pytest.raises(LeaseConflict):
            JobRepository(stale, clock=lambda: NOW).progress(initial.id, "worker-0", initial.lease_token, 1, 0.5)
    assert snapshot(factory)["revision"] == 2
    assert snapshot(factory)["progress"] == 0


def test_renewal_never_shortens_existing_lease(factory: sessionmaker[Session]) -> None:
    seed(factory)
    initial = claim(factory)
    with factory() as session:
        renewed = JobRepository(session, clock=lambda: NOW + timedelta(seconds=1)).renew(
            initial.id, "worker-0", initial.lease_token, 1, 5
        )
    assert renewed.lease_expires_at == initial.lease_expires_at


@pytest.mark.parametrize("operation", ["complete", "fail"])
def test_finishing_a_running_job_persists_terminal_state(factory: sessionmaker[Session], operation: str) -> None:
    seed(factory)
    initial = claim(factory)
    with factory() as session:
        repository = JobRepository(session, clock=lambda: NOW)
        repository.progress(initial.id, "worker-0", initial.lease_token, 1, 0.5)
        if operation == "complete":
            finished = repository.complete(initial.id, "worker-0", initial.lease_token, 2)
        else:
            finished = repository.fail(initial.id, "worker-0", initial.lease_token, 2, "COPY_INTERRUPTED")
    row = snapshot(factory)
    assert finished.status == (JobStatus.COMPLETE if operation == "complete" else JobStatus.FAILED)
    assert finished.revision == 3
    assert row["progress"] == (1 if operation == "complete" else 0.5)
    assert row["error"] == (None if operation == "complete" else "COPY_INTERRUPTED")
    assert row["lease_worker_id"] is None
    assert row["lease_token_digest"] is None
    assert row["lease_expires_at"] is None
    with factory() as session, pytest.raises(LeaseConflict):
        JobRepository(session, clock=lambda: NOW).progress(initial.id, "worker-0", initial.lease_token, 3, 0.6)


@pytest.mark.parametrize("operation", ["complete", "fail"])
@pytest.mark.parametrize("invalid", ["worker", "token", "revision", "expired"])
def test_finalization_rejects_invalid_lease_without_writes(
    factory: sessionmaker[Session], operation: str, invalid: str
) -> None:
    seed(factory)
    initial = claim(factory)
    with factory() as session:
        JobRepository(session, clock=lambda: NOW).progress(initial.id, "worker-0", initial.lease_token, 1, 0.5)
    before = snapshot(factory)
    worker = "worker-1" if invalid == "worker" else "worker-0"
    token = "wrong" if invalid == "token" else initial.lease_token
    revision = 1 if invalid == "revision" else 2
    now = NOW + timedelta(seconds=30 if invalid == "expired" else 1)
    with factory() as session, pytest.raises(LeaseConflict):
        repository = JobRepository(session, clock=lambda: now)
        if operation == "complete":
            repository.complete(initial.id, worker, token, revision)
        else:
            repository.fail(initial.id, worker, token, revision, "COPY_INTERRUPTED")
    assert snapshot(factory) == before


def test_completion_cannot_skip_running_transition(factory: sessionmaker[Session]) -> None:
    from drone_media_manager.domain.errors import InvalidTransition

    seed(factory)
    initial = claim(factory)
    before = snapshot(factory)
    with factory() as session, pytest.raises(InvalidTransition):
        JobRepository(session, clock=lambda: NOW).complete(initial.id, "worker-0", initial.lease_token, 1)
    assert snapshot(factory) == before


def test_failure_is_allowed_before_first_progress(factory: sessionmaker[Session]) -> None:
    seed(factory)
    initial = claim(factory)
    with factory() as session:
        result = JobRepository(session, clock=lambda: NOW).fail(initial.id, "worker-0", initial.lease_token, 1, "PREFLIGHT_FAILED")
    assert result.status == JobStatus.FAILED
    assert snapshot(factory)["error"] == "PREFLIGHT_FAILED"
