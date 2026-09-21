"""End-to-end worker API behavior against migrated SQLite."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from drone_media_manager.api.app import create_app
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.core import AuditEvent, Job, Worker
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.domain.enums import JobStatus, WorkerStatus

NOW = datetime.now(UTC)


@pytest.fixture
def api(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, sessionmaker[Session], ServerSettings]]:
    settings = ServerSettings(
        database_path=tmp_path / "api.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("bootstrap-token-that-is-at-least-32-chars"),
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["server_settings"] = settings
    command.upgrade(config, "head")
    engine = create_engine_from_settings(settings)
    factory = session_factory(engine)
    with TestClient(create_app(settings, factory), raise_server_exceptions=False) as client:
        yield client, factory, settings
    engine.dispose()


def test_registration_rejects_wrong_bootstrap_token(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, _ = api
    response = client.post(
        "/api/workers/register",
        headers={"Authorization": "Bearer wrong"},
        json={"name": "windows-laptop", "capabilities": ["ingest"]},
    )
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "invalid_bootstrap_token"}}


def register(client: TestClient, settings: ServerSettings, *, name: str = "windows-laptop", capabilities: list[str] | None = None) -> tuple[str, str]:
    response = client.post(
        "/api/workers/register",
        headers={"Authorization": f"Bearer {settings.worker_bootstrap_token.get_secret_value()}"},
        json={"name": name, "capabilities": capabilities or ["ingest"]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["worker_id"], body["worker_token"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def seed_job(factory: sessionmaker[Session], *, job_id: str = "job-1") -> None:
    with factory.begin() as session:
        session.add(
            Job(
                id=job_id,
                kind="ingest",
                payload_json='{"source_id":"source-1"}',
                status=JobStatus.PENDING,
                available_at=NOW,
                created_at=NOW,
            )
        )


def claim_job(client: TestClient, worker_id: str, token: str) -> dict[str, object]:
    response = client.post(
        "/api/worker-jobs/claim",
        headers=auth(token),
        json={
            "worker_id": worker_id,
            "idempotency_key": str(uuid4()),
            "lease_seconds": 60,
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, object], response.json())


def test_registration_returns_token_once_and_persists_digest_and_audit(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = api
    worker_id, token = register(client, settings)
    assert len(bytes.fromhex(token)) == 32
    with factory() as session:
        worker = session.get(Worker, worker_id)
        assert worker is not None
        assert worker.token_digest == hashlib.sha256(token.encode()).hexdigest()
        assert token not in repr(worker)
        assert json.loads(worker.capabilities_json) == ["ingest"]
        event = session.scalars(select(AuditEvent)).one()
        assert (event.action, event.entity_id, event.result) == (
            "worker.register",
            worker_id,
            "accepted",
        )
        assert token not in event.details_json


def test_heartbeat_updates_worker_and_audit_atomically(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = api
    worker_id, token = register(client, settings)
    response = client.post(
        f"/api/workers/{worker_id}/heartbeat", headers=auth(token), json={}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ONLINE"
    assert body["revision"] == 1
    assert body["last_seen_at"].endswith("Z")
    with factory() as session:
        worker = session.get(Worker, worker_id)
        events = session.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at)).all()
        assert worker is not None
        assert worker.status == WorkerStatus.ONLINE
        assert worker.revision == 1
        assert [event.action for event in events] == ["worker.register", "worker.heartbeat"]


def test_claim_uses_persisted_worker_capabilities_and_audits_correlation(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = api
    worker_id, token = register(client, settings)
    seed_job(factory)
    correlation_id = str(uuid4())
    response = client.post(
        "/api/worker-jobs/claim",
        headers=auth(token),
        json={"worker_id": worker_id, "idempotency_key": correlation_id, "lease_seconds": 60},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job-1"
    assert body["status"] == "LEASED"
    assert body["revision"] == 1
    assert body["payload"] == {"source_id": "source-1"}
    assert len(bytes.fromhex(body["lease_token"])) == 32
    with factory() as session:
        worker = session.get(Worker, worker_id)
        event = session.scalars(select(AuditEvent).where(AuditEvent.action == "job.claim")).one()
        assert worker is not None and worker.status == WorkerStatus.BUSY
        assert event.correlation_id == correlation_id
        assert body["lease_token"] not in event.details_json


def test_no_eligible_job_returns_204_without_success_audit(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = api
    worker_id, token = register(client, settings, capabilities=["analyze"])
    seed_job(factory)
    response = client.post(
        "/api/worker-jobs/claim",
        headers=auth(token),
        json={"worker_id": worker_id, "idempotency_key": str(uuid4()), "lease_seconds": 60},
    )
    assert response.status_code == 204
    with factory() as session:
        job = session.scalar(select(Job).where(Job.id == "job-1"))
        assert job is not None
        assert job.status == JobStatus.PENDING
        assert session.scalars(select(AuditEvent).where(AuditEvent.action == "job.claim")).all() == []


def test_heartbeat_preserves_busy_state_until_job_finishes(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = api
    worker_id, token = register(client, settings)
    seed_job(factory)
    claim_job(client, worker_id, token)
    response = client.post(
        f"/api/workers/{worker_id}/heartbeat", headers=auth(token), json={}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "BUSY"


def test_progress_then_complete_full_contract(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = api
    worker_id, token = register(client, settings)
    seed_job(factory)
    claimed = claim_job(client, worker_id, token)
    progress_key = str(uuid4())
    progress = client.post(
        "/api/worker-jobs/job-1/progress",
        headers=auth(token),
        json={
            "worker_id": worker_id,
            "lease_token": claimed["lease_token"],
            "revision": 1,
            "progress": 0.5,
            "idempotency_key": progress_key,
        },
    )
    assert progress.status_code == 200
    assert progress.json() == {
        "job_id": "job-1",
        "status": "RUNNING",
        "revision": 2,
        "progress": 0.5,
    }
    complete_key = str(uuid4())
    completed = client.post(
        "/api/worker-jobs/job-1/complete",
        headers=auth(token),
        json={
            "worker_id": worker_id,
            "lease_token": claimed["lease_token"],
            "revision": 2,
            "idempotency_key": complete_key,
        },
    )
    assert completed.status_code == 200
    assert completed.json() == {
        "job_id": "job-1",
        "status": "COMPLETE",
        "revision": 3,
        "progress": 1.0,
    }
    with factory() as session:
        events = session.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == "job-1").order_by(AuditEvent.occurred_at)
        ).all()
        assert [(event.action, event.correlation_id) for event in events] == [
            ("job.claim", events[0].correlation_id),
            ("job.progress", progress_key),
            ("job.complete", complete_key),
        ]
        worker = session.get(Worker, worker_id)
        assert worker is not None
        assert worker.status == WorkerStatus.ONLINE


def test_fail_sanitizes_bounded_error_details(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = api
    worker_id, token = register(client, settings)
    seed_job(factory)
    claimed = claim_job(client, worker_id, token)
    secret = "highly-sensitive-value"
    response = client.post(
        "/api/worker-jobs/job-1/fail",
        headers=auth(token),
        json={
            "worker_id": worker_id,
            "lease_token": claimed["lease_token"],
            "revision": 1,
            "idempotency_key": str(uuid4()),
            "error": f"COPY_FAILED\nBearer {secret} token={secret}",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    with factory() as session:
        job = session.get(Job, "job-1")
        event = session.scalars(select(AuditEvent).where(AuditEvent.action == "job.fail")).one()
        assert job is not None
        assert job.error is not None
        assert secret not in job.error
        assert secret not in event.details_json
        assert "\n" not in job.error


def test_stale_expired_and_invalid_transition_have_stable_conflict_codes(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = api
    worker_id, token = register(client, settings)
    seed_job(factory)
    claimed = claim_job(client, worker_id, token)
    common = {
        "worker_id": worker_id,
        "lease_token": claimed["lease_token"],
        "idempotency_key": str(uuid4()),
    }
    stale = client.post(
        "/api/worker-jobs/job-1/progress",
        headers=auth(token),
        json={**common, "revision": 0, "progress": 0.5},
    )
    assert stale.status_code == 409
    assert stale.json() == {"error": {"code": "stale_revision"}}
    invalid = client.post(
        "/api/worker-jobs/job-1/complete",
        headers=auth(token),
        json={**common, "revision": 1},
    )
    assert invalid.status_code == 409
    assert invalid.json() == {"error": {"code": "invalid_transition"}}
    with factory.begin() as session:
        job = session.get(Job, "job-1")
        assert job is not None
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    expired = client.post(
        "/api/worker-jobs/job-1/progress",
        headers=auth(token),
        json={**common, "revision": 1, "progress": 0.5},
    )
    assert expired.status_code == 409
    assert expired.json() == {"error": {"code": "expired_lease"}}


def test_audit_insert_failure_rolls_back_heartbeat(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = api
    worker_id, token = register(client, settings)
    with factory.begin() as session:
        session.execute(
            text(
                "CREATE TRIGGER reject_api_audit BEFORE INSERT ON audit_events "
                "BEGIN SELECT RAISE(ABORT, 'audit rejected'); END"
            )
        )
    response = client.post(
        f"/api/workers/{worker_id}/heartbeat", headers=auth(token), json={}
    )
    assert response.status_code == 500
    with factory() as session:
        worker = session.get(Worker, worker_id)
        assert worker is not None
        assert worker.status == WorkerStatus.OFFLINE
        assert worker.revision == 0
