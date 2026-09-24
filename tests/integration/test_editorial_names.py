"""Phase 3B confirms suggestions without requiring SRT or network access."""

import re
from pathlib import Path

from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch

from drone_media_manager.api.app import create_app
from drone_media_manager.auth.passwords import hash_password
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.auth import User, UserSession
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.grouping.models import LocationGroup
from drone_media_manager.grouping.names import GooglePlacesProvider, NameCandidate


def test_srt_candidate_confirmation_edit_and_manual_no_srt(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
        google_maps_api_key=SecretStr("test-key"),
    )
    settings.omv_root.mkdir()
    (settings.omv_root / "DJI_0001.srt").write_text(
        "1\n00:00:00,000 --> 00:00:00,033\n"
        "2026-09-01 10:00:00 [latitude: -3.85] [longitude: -32.42]\n"
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with sessions() as session:
        trip = Trip(name="Viagem", slug="viagem", nas_rel_path="viagem")
        session.add_all(
            [
                trip,
                User(
                    username="editor", password_hash=hash_password("valid password 123")
                ),
            ]
        )
        session.flush()
        for n in (1, 2):
            asset = CatalogAsset(
                asset_id=f"{n:064x}",
                trip_id=trip.id,
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
                    rel_path=f"DJI_{n:04}.mp4",
                    sha256="a" * 64,
                    availability_status="AVAILABLE",
                )
            )
            if n == 1:
                session.add(
                    AssetFile(
                        catalog_asset_id=asset.id,
                        role="SRT",
                        rel_path="DJI_0001.srt",
                        sha256="b" * 64,
                        availability_status="AVAILABLE",
                    )
                )
        session.commit()
        trip_id = trip.id

    calls: list[tuple[float, float, int]] = []

    def fake_places(
        _self: GooglePlacesProvider, lat: float, lon: float, radius: int
    ) -> list[NameCandidate]:
        calls.append((lat, lon, radius))
        return [NameCandidate("Praia do Bode", "google-place-1")]

    monkeypatch.setattr(GooglePlacesProvider, "suggest_names", fake_places)
    client = TestClient(create_app(settings, sessions), base_url="https://testserver")
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token is not None
    assert (
        client.post(
            "/login",
            data={
                "username": "editor",
                "password": "valid password 123",
                "csrf_token": token[1],
            },
            headers={"Origin": "https://testserver"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    with sessions() as session:
        csrf = session.query(UserSession).one().csrf_token
    headers = {"X-CSRF-Token": csrf, "Origin": "https://testserver"}
    assert (
        client.post(
            f"/api/editorial/trips/{trip_id}/analyze", headers=headers
        ).status_code
        == 200
    )
    assets = client.get(f"/api/editorial/trips/{trip_id}").json()["assets"]
    url = f"/api/editorial/trips/{trip_id}/name-suggestions"
    first = {"start_asset_id": assets[0]["id"], "end_asset_id": assets[0]["id"]}
    suggested = client.get(url, params=first)
    assert suggested.status_code == 200
    assert suggested.json()["candidates"] == [
        {"name": "Praia do Bode", "place_id": "google-place-1"}
    ]
    assert client.get(url, params=first).json() == suggested.json()
    assert calls == [(-3.85, -32.42, 500)]
    created = client.post(
        f"/api/editorial/trips/{trip_id}/groups",
        json={**first, "name": "Praia do Bode", "place_id": "google-place-1"},
        headers=headers,
    )
    assert created.status_code == 201
    group_id = created.json()["id"]
    with sessions() as session:
        group = session.get(LocationGroup, group_id)
        assert group is not None
        assert (group.name_final, group.name_source, group.provider_place_id) == (
            "Praia do Bode",
            "GOOGLE_PLACES_CONFIRMED",
            "google-place-1",
        )
    edited = client.patch(
        f"/api/editorial/trips/{trip_id}/groups/{group_id}/name",
        json={"name": "Pôr do Sol"},
        headers=headers,
    )
    assert edited.status_code == 200
    with sessions() as session:
        group = session.get(LocationGroup, group_id)
        assert group is not None
        assert (group.name_final, group.name_source, group.provider_place_id) == (
            "Pôr do Sol",
            "HUMAN",
            None,
        )
    second = {"start_asset_id": assets[1]["id"], "end_asset_id": assets[1]["id"]}
    assert client.get(url, params=second).json()["candidates"] == []
    manual = client.post(
        f"/api/editorial/trips/{trip_id}/groups",
        json={**second, "name": "Barco Esmeralda"},
        headers=headers,
    )
    assert manual.status_code == 201
    assert manual.json()["name"] == "Barco Esmeralda"
    assert len(calls) == 1
    engine.dispose()
