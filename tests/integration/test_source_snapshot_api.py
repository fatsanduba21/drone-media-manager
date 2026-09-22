"""Worker-owned immutable source snapshot API integration tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from drone_media_manager.api.app import create_app
from drone_media_manager.config import ServerSettings
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


def _register(
    client: TestClient, settings: ServerSettings, name: str
) -> tuple[str, str]:
    response = client.post(
        "/api/workers/register",
        headers=_auth(settings.worker_bootstrap_token.get_secret_value()),
        json={"name": name, "capabilities": ["ingest"]},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return body["worker_id"], body["worker_token"]


def _snapshot_request(
    worker_id: str, *, expires_at: datetime | None = None
) -> dict[str, object]:
    return {
        "worker_id": worker_id,
        "source_kind": "LOCAL",
        "source_volume_identity": "volume-1",
        "expires_at": (
            expires_at or datetime.now(UTC) + timedelta(minutes=5)
        ).isoformat(),
    }


def test_worker_cannot_submit_snapshot_for_another_worker(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, settings = api
    _, token_a = _register(client, settings, "worker-a")
    worker_b, _ = _register(client, settings, "worker-b")
    response = client.post(
        "/api/sources/snapshots",
        headers=_auth(token_a),
        json=_snapshot_request(worker_b),
    )

    assert response.status_code == 403


def test_snapshot_finalization_recomputes_count_and_fingerprint(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, settings = api
    worker_id, token = _register(client, settings, "worker")
    created = client.post(
        "/api/sources/snapshots",
        headers=_auth(token),
        json=_snapshot_request(worker_id),
    )
    assert created.status_code == 201, created.text
    snapshot = created.json()

    added = client.post(
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
    )
    assert added.status_code == 200, added.text
    revised = added.json()

    finalized = client.post(
        f"/api/sources/snapshots/{snapshot['snapshot_id']}/finalize",
        headers=_auth(token),
        json={
            "worker_id": worker_id,
            "revision": revised["revision"],
            "declared_item_count": 1,
        },
    )

    assert finalized.status_code == 200, finalized.text
    body = finalized.json()
    assert body["status"] == "FINALIZED"
    assert body["declared_item_count"] == 1
    assert len(body["source_fingerprint"]) == 64


def test_snapshot_rejects_more_than_500_entries(
    api: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, settings = api
    worker_id, token = _register(client, settings, "worker")
    created = client.post(
        "/api/sources/snapshots",
        headers=_auth(token),
        json=_snapshot_request(worker_id),
    )
    snapshot = created.json()
    entries = [
        {
            "source_rel_path": f"DCIM/{index}.MP4",
            "size_bytes": 1,
            "mtime_ns": 1,
            "file_identity": str(index),
        }
        for index in range(501)
    ]

    response = client.post(
        f"/api/sources/snapshots/{snapshot['snapshot_id']}/entries",
        headers=_auth(token),
        json={"worker_id": worker_id, "revision": 0, "entries": entries},
    )

    assert response.status_code == 422
