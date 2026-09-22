"""Distributed server/worker checkpoint using only local in-memory test state."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from drone_media_manager.api.app import create_app
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.core import Job, Worker
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.domain.enums import JobStatus, WorkerStatus
from drone_media_manager.worker.client import WorkerApiClient


@pytest.fixture
def server(
    tmp_path: Path,
) -> Iterator[tuple[ServerSettings, sessionmaker[Session], TestClient]]:
    settings = ServerSettings(
        database_path=tmp_path / "server.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("bootstrap-token-that-is-at-least-32-chars"),
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["server_settings"] = settings
    command.upgrade(config, "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with TestClient(create_app(settings, sessions)) as client:
        yield settings, sessions, client
    engine.dispose()


def test_worker_registers_heartbeats_and_claims_health_check_job(
    server: tuple[ServerSettings, sessionmaker[Session], TestClient],
) -> None:
    settings, sessions, test_client = server
    http_client = httpx.Client(
        transport=test_client._transport,
        base_url="http://testserver",
    )

    bootstrap_client = WorkerApiClient(
        "http://testserver",
        settings.worker_bootstrap_token.get_secret_value(),
        http_client=http_client,
    )
    identity = bootstrap_client.register("windows-laptop", ["health-check"])
    worker_client = WorkerApiClient(
        "http://testserver",
        identity.worker_token,
        http_client=http_client,
    )

    heartbeat = worker_client.heartbeat(identity.worker_id)
    assert heartbeat.status == WorkerStatus.ONLINE

    with sessions.begin() as session:
        session.add(
            Job(
                id="health-check-job",
                kind="health-check",
                payload_json=json.dumps({"synthetic": True}),
                status=JobStatus.PENDING,
                available_at=datetime.now(UTC),
            )
        )

    claimed = worker_client.claim(identity.worker_id)

    assert claimed is not None
    assert claimed.kind == "health-check"
    assert claimed.payload == {"synthetic": True}
    with sessions() as session:
        worker = session.get(Worker, identity.worker_id)
        assert worker is not None
        assert worker.status == WorkerStatus.BUSY
