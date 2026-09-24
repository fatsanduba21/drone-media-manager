"""Remote editorial access uses the existing HTTPS browser session."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from drone_media_manager.api.app import create_app
from drone_media_manager.auth.passwords import hash_password
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.auth import User, UserSession
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset
from drone_media_manager.db.models.core import AuditEvent
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory

PASSWORD = "correct horse battery staple"


@pytest.fixture
def remote_editorial(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, sessionmaker[Session], str, str]]:
    settings = ServerSettings(
        database_path=tmp_path / "editorial.sqlite3",
        omv_root=tmp_path / "omv",
        bind_host="0.0.0.0",
        tls_certfile=tmp_path / "server.crt",
        tls_keyfile=tmp_path / "server.key",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with sessions() as session:
        user = User(username="editor", password_hash=hash_password(PASSWORD))
        trip = Trip(name="Viagem", slug="viagem", nas_rel_path="viagem")
        session.add_all([user, trip])
        session.flush()
        asset = CatalogAsset(
            asset_id="a" * 64,
            trip_id=trip.id,
            media_type="PHOTO",
            classification="FOTOS",
            verification_status="VERIFIED",
        )
        session.add(asset)
        session.flush()
        session.add(
            AssetFile(
                catalog_asset_id=asset.id,
                role="ORIGINAL",
                rel_path="viagem/DJI_0001.JPG",
                sha256="b" * 64,
                availability_status="AVAILABLE",
            )
        )
        session.commit()
        trip_id, asset_id = trip.id, asset.id
    with TestClient(
        create_app(settings, sessions), base_url="https://testserver"
    ) as client:
        yield client, sessions, trip_id, asset_id
    engine.dispose()


def login(client: TestClient) -> None:
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token is not None
    response = client.post(
        "/login",
        data={"username": "editor", "password": PASSWORD, "csrf_token": token[1]},
        headers={"Origin": "https://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_remote_editorial_requires_https_login(
    remote_editorial: tuple[TestClient, sessionmaker[Session], str, str],
) -> None:
    client, _, trip_id, asset_id = remote_editorial
    assert client.get("/editorial/", follow_redirects=False).status_code == 303
    assert client.get("/api/editorial/trips").status_code == 401
    assert client.get(f"/api/editorial/assets/{asset_id}/thumbnail").status_code == 401
    assert client.post(f"/api/editorial/trips/{trip_id}/analyze").status_code == 401
    login(client)
    assert "Shift + clique" in client.get("/editorial/").text
    assert client.get("/api/editorial/trips").status_code == 200
    token = client.cookies.get("__Host-dmm_session")
    assert token is not None
    with TestClient(client.app, base_url="http://testserver") as insecure:
        assert (
            insecure.get(
                "/editorial/", cookies={"__Host-dmm_session": token}
            ).status_code
            == 426
        )
        assert (
            insecure.get(
                "/api/editorial/trips", cookies={"__Host-dmm_session": token}
            ).status_code
            == 426
        )


def test_remote_editorial_mutations_require_csrf(
    remote_editorial: tuple[TestClient, sessionmaker[Session], str, str],
) -> None:
    client, sessions, trip_id, asset_id = remote_editorial
    login(client)
    with sessions() as session:
        csrf = session.query(UserSession).one().csrf_token
    headers = {"X-CSRF-Token": csrf, "Origin": "https://testserver"}
    analyze_url = f"/api/editorial/trips/{trip_id}/analyze"
    assert client.post(analyze_url).status_code == 403
    assert client.post(analyze_url, headers=headers).status_code == 200
    url = f"/api/editorial/trips/{trip_id}/groups"
    payload = {
        "start_asset_id": asset_id,
        "end_asset_id": asset_id,
        "name": "Praia",
    }
    assert client.post(url, json=payload).status_code == 403
    assert (
        client.post(
            url,
            json=payload,
            headers={**headers, "Origin": "https://elsewhere.example"},
        ).status_code
        == 403
    )
    created = client.post(url, json=payload, headers=headers)
    assert created.status_code == 201
    assert created.json()["name"] == "Praia"
    with sessions() as session:
        assert session.query(AuditEvent).filter_by(
            action="location_group.create"
        ).one().actor == (session.query(User).one().id)
    group_url = f"{url}/{created.json()['id']}"
    assert client.put(group_url, json=payload).status_code == 403
    assert client.put(group_url, json=payload, headers=headers).status_code == 200
    page = client.get("/editorial/")
    assert f'name="dmm-csrf-token" content="{csrf}"' in page.text
