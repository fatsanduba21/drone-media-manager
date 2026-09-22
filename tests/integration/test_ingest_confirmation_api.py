"""Local-admin confirmation integration tests for safe ingest."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from drone_media_manager.api.app import create_app
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.core import Job
from drone_media_manager.db.models.ingest import IngestItem, Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory


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
    with TestClient(create_app(settings, factory)) as client:
        yield client, factory, settings
    engine.dispose()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _finalized_snapshot(client: TestClient, settings: ServerSettings) -> str:
    registered = client.post(
        "/api/workers/register",
        headers=_auth(settings.worker_bootstrap_token.get_secret_value()),
        json={"name": "worker", "capabilities": ["ingest"]},
    ).json()
    worker_id, token = registered["worker_id"], registered["worker_token"]
    snapshot = client.post(
        "/api/sources/snapshots",
        headers=_auth(token),
        json={
            "worker_id": worker_id,
            "source_kind": "LOCAL",
            "source_volume_identity": "volume-1",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
        },
    ).json()
    entries = client.post(
        f"/api/sources/snapshots/{snapshot['snapshot_id']}/entries",
        headers=_auth(token),
        json={
            "worker_id": worker_id,
            "revision": snapshot["revision"],
            "entries": [
                {
                    "source_rel_path": "DCIM/DJI_0001.MP4",
                    "size_bytes": 5,
                    "mtime_ns": 10,
                    "file_identity": "file-1",
                    "pair_status": "VIDEO_WITHOUT_SRT",
                }
            ],
        },
    ).json()
    finalized = client.post(
        f"/api/sources/snapshots/{snapshot['snapshot_id']}/finalize",
        headers=_auth(token),
        json={
            "worker_id": worker_id,
            "revision": entries["revision"],
            "declared_item_count": 1,
        },
    )
    assert finalized.status_code == 200, finalized.text
    return finalized.json()["snapshot_id"]


def _trip(factory: sessionmaker[Session]) -> Trip:
    trip = Trip(name="Trip", slug="trip", nas_rel_path="trips/trip")
    with factory.begin() as session:
        session.add(trip)
    return trip


def test_confirmed_snapshot_enqueues_ingest_job(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = api
    snapshot_id = _finalized_snapshot(client, settings)
    trip = _trip(factory)

    response = client.post(
        "/api/ingests",
        json={"snapshot_id": snapshot_id, "trip_id": trip.id, "revision": 2},
    )

    assert response.status_code == 201, response.text
    assert response.json()["status"] == "DISCOVERED"
    with factory() as session:
        assert len(session.scalars(select(IngestItem)).all()) == 1
        jobs = session.scalars(select(Job)).all()
    assert len(jobs) == 1 and jobs[0].kind == "ingest"


def test_confirmation_is_idempotent_and_rejects_stale_revision(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, factory, settings = api
    snapshot_id = _finalized_snapshot(client, settings)
    trip = _trip(factory)
    request = {"snapshot_id": snapshot_id, "trip_id": trip.id, "revision": 2}

    first = client.post("/api/ingests", json=request)
    replay = client.post("/api/ingests", json=request)
    stale = client.post("/api/ingests", json={**request, "revision": 1})

    assert first.status_code == replay.status_code == 201
    assert first.json()["ingest_id"] == replay.json()["ingest_id"]
    assert stale.status_code == 409

    with factory() as session:
        assert len(session.scalars(select(Job)).all()) == 1


def test_confirmation_is_not_exposed_on_a_lan_bind(tmp_path: Path) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "api.sqlite3",
        omv_root=tmp_path / "omv",
        bind_host="0.0.0.0",
        allow_insecure_lan=True,
        worker_bootstrap_token=SecretStr("bootstrap-token-that-is-at-least-32-chars"),
    )
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.attributes["server_settings"] = settings
    command.upgrade(config, "head")
    engine = create_engine_from_settings(settings)
    factory = session_factory(engine)
    with TestClient(create_app(settings, factory)) as client:
        response = client.post(
            "/api/ingests",
            json={"snapshot_id": "missing", "trip_id": "missing", "revision": 0},
        )
    engine.dispose()

    assert response.status_code == 403
    assert response.json() == {"error": {"code": "localhost_admin_required"}}
