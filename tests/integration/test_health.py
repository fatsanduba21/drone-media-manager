from __future__ import annotations

from collections.abc import Iterator
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
def health_api(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    database_path = tmp_path / "health.sqlite3"
    omv_root = tmp_path / "omv"
    omv_root.mkdir()
    settings = ServerSettings(
        database_path=database_path,
        omv_root=omv_root,
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    alembic = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    alembic.attributes["server_settings"] = settings
    command.upgrade(alembic, "head")
    engine = create_engine_from_settings(settings)
    sessions: sessionmaker[Session] = session_factory(engine)
    with TestClient(create_app(settings, sessions)) as client:
        yield client, omv_root
    engine.dispose()


def test_health_separates_dependencies_and_does_not_create_omv_files(
    health_api: tuple[TestClient, Path],
) -> None:
    client, omv_root = health_api

    before = sorted(path.relative_to(omv_root) for path in omv_root.rglob("*"))
    response = client.get("/health")
    after = sorted(path.relative_to(omv_root) for path in omv_root.rglob("*"))

    assert response.status_code == 200
    body = response.json()
    assert set(body["components"]) == {
        "database",
        "omv",
        "ffmpeg",
        "ffprobe",
        "worker_summary",
    }
    assert body["components"]["omv"]["state"] in {"healthy", "degraded"}
    assert before == after
