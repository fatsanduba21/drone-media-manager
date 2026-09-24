"""The 3A review API serves thumbnails and accepts human range corrections."""

from pathlib import Path

from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr

from drone_media_manager.api.app import create_app
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset, Derivative
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory


def test_legacy_gallery_and_range_update(tmp_path: Path) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=tmp_path / "omv",
        derivatives_root=tmp_path / "cache",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with sessions() as session:
        trip = Trip(name="Legado", slug="legado", nas_rel_path="legado")
        session.add(trip)
        session.flush()
        for n in (1, 2, 3):
            asset = CatalogAsset(
                asset_id=f"{n:064x}",
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
                    rel_path=f"DJI_{n:04}.JPG",
                    sha256="a" * 64,
                    availability_status="AVAILABLE",
                )
            )
            path = settings.derivatives_root / f"{n}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"jpeg-data")
            session.add(
                Derivative(
                    catalog_asset_id=asset.id,
                    kind="THUMBNAIL",
                    status="READY",
                    profile_version="grid-v1",
                    source_sha256="a" * 64,
                    rel_path=path.name,
                    output_sha256="b" * 64,
                )
            )
        session.commit()
        trip_id = trip.id
    client = TestClient(create_app(settings, sessions))
    page = client.get("/editorial/")
    assert page.status_code == 200
    assert "Shift + clique" in page.text
    state = client.get(f"/api/editorial/trips/{trip_id}")
    assert state.status_code == 200
    assets = state.json()["assets"]
    assert [item["filename"] for item in assets] == [
        "DJI_0001.JPG",
        "DJI_0002.JPG",
        "DJI_0003.JPG",
    ]
    assert client.get(assets[0]["thumbnail_url"]).content == b"jpeg-data"
    with sessions() as session:
        derivative = (
            session.query(Derivative).filter_by(catalog_asset_id=assets[0]["id"]).one()
        )
        derivative.rel_path = "../outside.jpg"
        session.commit()
    assert client.get(assets[0]["thumbnail_url"]).status_code == 404
    created = client.post(
        f"/api/editorial/trips/{trip_id}/groups",
        json={
            "start_asset_id": assets[0]["id"],
            "end_asset_id": assets[1]["id"],
            "name": "Casa",
        },
    )
    assert created.status_code == 201
    group_id = created.json()["id"]
    corrected = client.put(
        f"/api/editorial/trips/{trip_id}/groups/{group_id}",
        json={"start_asset_id": assets[1]["id"], "end_asset_id": assets[2]["id"]},
    )
    assert corrected.status_code == 200
    assert [
        item["location_group_id"]
        for item in client.get(f"/api/editorial/trips/{trip_id}").json()["assets"]
    ] == [None, group_id, group_id]
    engine.dispose()
