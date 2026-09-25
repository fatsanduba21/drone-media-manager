"""Phase 3D edits only selected catalog rows, even without SRT or internet."""

from __future__ import annotations

import re
from pathlib import Path

from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from drone_media_manager.api.app import create_app
from drone_media_manager.auth.passwords import hash_password
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.auth import User, UserSession
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.editorial.models import EditorialField, EditorialTag


def test_batch_fields_are_atomic_and_preserve_unspecified_values(
    tmp_path: Path,
) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=tmp_path / "offline",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with sessions() as session:
        trip = Trip(name="Viagem", slug="viagem", nas_rel_path="missing")
        other = Trip(name="Outra", slug="outra", nas_rel_path="missing2")
        session.add_all(
            [
                trip,
                other,
                User(
                    username="editor", password_hash=hash_password("valid password 123")
                ),
            ]
        )
        session.flush()
        ids = []
        for n in range(3):
            asset = CatalogAsset(
                asset_id=f"{n + 1:064x}",
                trip_id=trip.id if n < 2 else other.id,
                media_type="VIDEO",
                classification="YOUTUBE_16X9",
                verification_status="VERIFIED",
            )
            session.add(asset)
            session.flush()
            session.add(
                AssetFile(
                    catalog_asset_id=asset.id,
                    role="ORIGINAL",
                    rel_path=f"clip{n}.mp4",
                    sha256="a" * 64,
                    availability_status="MISSING",
                )
            )
            ids.append(asset.id)
        session.commit()
        trip_id = trip.id
    client = TestClient(create_app(settings, sessions), base_url="https://testserver")
    page = client.get("/login")
    csrf_login = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert csrf_login
    assert (
        client.post(
            "/login",
            data={
                "username": "editor",
                "password": "valid password 123",
                "csrf_token": csrf_login[1],
            },
            headers={"Origin": "https://testserver"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    with sessions() as session:
        csrf = session.query(UserSession).one().csrf_token
    headers = {"X-CSRF-Token": csrf, "Origin": "https://testserver"}
    url = f"/api/editorial/trips/{trip_id}/assets"
    payload = {
        "asset_ids": ids[:2],
        "people": "YES",
        "subject": "Barco",
        "people_label": "Nosso grupo",
        "movement": "ORBITA",
        "add_tags": ["Pôr do sol", "barco"],
    }
    assert client.patch(url, json=payload).status_code == 403
    assert (
        client.patch(
            url, json={**payload, "asset_ids": [ids[0], ids[2]]}, headers=headers
        ).status_code
        == 422
    )
    assert client.patch(url, json=payload, headers=headers).json() == {"updated": 2}
    state = client.get(f"/api/editorial/trips/{trip_id}").json()["assets"]
    assert all(
        row["people_final"] == "YES" and row["subject_final"] == "Barco"
        for row in state
    )
    assert all(
        row["movement_final"] == "ORBITA" and row["people_label"] == "Nosso grupo"
        for row in state
    )
    assert all(row["tags"] == ["barco", "pôr do sol"] for row in state)
    assert (
        client.patch(
            url,
            json={"asset_ids": [ids[0]], "people": "NO", "remove_tags": ["BARCO"]},
            headers=headers,
        ).status_code
        == 200
    )
    state = client.get(f"/api/editorial/trips/{trip_id}").json()["assets"]
    assert state[0]["people_final"] == "NO" and state[1]["people_final"] == "YES"
    assert (
        state[0]["subject_final"] == "Barco" and state[0]["movement_final"] == "ORBITA"
    )
    assert state[0]["tags"] == ["pôr do sol"] and len(state[1]["tags"]) == 2
    with sessions() as session:
        assert len(session.scalars(select(EditorialField)).all()) == 6
        assert len(session.scalars(select(EditorialTag)).all()) == 3
        assert session.get(CatalogAsset, ids[2]).people is None
    engine.dispose()
