"""Read-only catalog, safe derivative serving, and browser navigation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from drone_media_manager.api.app import create_app
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import CatalogAsset, Derivative
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory

TRIP = "teste-fase-1"
PORTRAIT = "a" * 64
LANDSCAPE = "b" * 64
PHOTO = "c" * 64
PROXY_BYTES = b"0123456789"
THUMB_BYTES = b"thumbnail-content"


@pytest.fixture
def catalog(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, sessionmaker[Session], ServerSettings]]:
    omv = tmp_path / "omv"
    omv.mkdir()
    settings = ServerSettings(
        database_path=tmp_path / "catalog.sqlite3",
        omv_root=omv,
        derivatives_root=tmp_path / "cache",
        worker_bootstrap_token=SecretStr("bootstrap-token-that-is-at-least-32-chars"),
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with sessions() as session:
        trip = Trip(name="Teste Fase 1", slug=TRIP, nas_rel_path=TRIP)
        session.add(trip)
        session.flush()
        for (
            asset_id,
            media_type,
            classification,
            poi,
            movement,
            people,
            width,
            height,
        ) in (
            (PORTRAIT, "VIDEO", "INSTAGRAM_9X16", "Praia", "orbit", "yes", 406, 720),
            (LANDSCAPE, "VIDEO", "YOUTUBE_16X9", "Montanha", "forward", "no", 720, 406),
            (PHOTO, "PHOTO", "FOTOS", "Praia", "still", "no", 400, 600),
        ):
            asset = CatalogAsset(
                asset_id=asset_id,
                trip_id=trip.id,
                media_type=media_type,
                classification=classification,
                duration_ms=12000 if media_type == "VIDEO" else None,
                poi_final=poi,
                movement=movement,
                people=people,
                display_width=width,
                display_height=height,
                verification_status="VERIFIED",
            )
            session.add(asset)
            session.flush()
            kinds = ("THUMBNAIL", "PROXY") if media_type == "VIDEO" else ("THUMBNAIL",)
            for kind in kinds:
                profile = "grid-v1" if kind == "THUMBNAIL" else "web-720p-v1"
                suffix = ".jpg" if kind == "THUMBNAIL" else ".mp4"
                payload = THUMB_BYTES if kind == "THUMBNAIL" else PROXY_BYTES
                rel_path = f"{asset_id[:2]}/{asset_id}/{profile}{suffix}"
                target = settings.derivatives_root / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                session.add(
                    Derivative(
                        catalog_asset_id=asset.id,
                        kind=kind,
                        status="READY",
                        profile_version=profile,
                        source_sha256="f" * 64,
                        rel_path=rel_path,
                        output_sha256=hashlib.sha256(payload).hexdigest(),
                        size_bytes=len(payload),
                    )
                )
        session.commit()
    with TestClient(create_app(settings, sessions)) as client:
        yield client, sessions, settings
    engine.dispose()


def test_trips_assets_and_detail_expose_metadata_without_filesystem_paths(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, settings = catalog
    trips = client.get("/api/catalog/trips")
    assert trips.status_code == 200
    assert trips.json()["trips"] == [
        {"slug": TRIP, "name": "Teste Fase 1", "asset_count": 3}
    ]
    trip = client.get(f"/api/catalog/trips/{TRIP}")
    assert trip.json() == {"slug": TRIP, "name": "Teste Fase 1", "asset_count": 3}

    listed = client.get(f"/api/catalog/trips/{TRIP}/assets")
    assert listed.status_code == 200
    assert listed.json()["total"] == 3
    assert {asset["asset_id"] for asset in listed.json()["assets"]} == {
        PORTRAIT,
        LANDSCAPE,
        PHOTO,
    }
    detail = client.get(f"/api/catalog/assets/{PORTRAIT}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["classification"] == "INSTAGRAM_9X16"
    assert body["duration_ms"] == 12000
    assert body["display_width"] == 406
    assert body["display_height"] == 720
    assert body["thumbnail_url"] == f"/api/catalog/assets/{PORTRAIT}/thumbnail"
    assert body["proxy_url"] == f"/api/catalog/assets/{PORTRAIT}/proxy"
    assert str(settings.derivatives_root) not in detail.text
    assert str(settings.omv_root) not in detail.text
    assert "rel_path" not in detail.text
    assert client.get("/api/catalog/trips/missing").status_code == 404
    assert client.get("/api/catalog/assets/" + "d" * 64).status_code == 404


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("classification=INSTAGRAM_9X16", {PORTRAIT}),
        ("poi=Praia", {PORTRAIT, PHOTO}),
        ("movement=orbit", {PORTRAIT}),
        ("people=yes", {PORTRAIT}),
        ("media_type=PHOTO", {PHOTO}),
        ("classification=INSTAGRAM_9X16&poi=Montanha", set()),
    ],
)
def test_assets_filter_by_each_editorial_field(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
    query: str,
    expected: set[str],
) -> None:
    client, _, _ = catalog
    response = client.get(f"/api/catalog/trips/{TRIP}/assets?{query}")
    assert response.status_code == 200
    assert {asset["asset_id"] for asset in response.json()["assets"]} == expected
    assert response.json()["total"] == len(expected)


def test_only_ready_derivatives_with_safe_registered_paths_are_served(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, sessions, _ = catalog
    assert client.get(f"/api/catalog/assets/{PHOTO}/proxy").status_code == 404
    assert (
        client.get("/api/catalog/assets/" + "d" * 64 + "/thumbnail").status_code == 404
    )
    with sessions() as session:
        thumbnail = session.scalar(
            select(Derivative)
            .join(CatalogAsset)
            .where(CatalogAsset.asset_id == PORTRAIT, Derivative.kind == "THUMBNAIL")
        )
        assert thumbnail is not None
        thumbnail.status = "ERROR"
        session.commit()
    assert client.get(f"/api/catalog/assets/{PORTRAIT}/thumbnail").status_code == 404

    with sessions() as session:
        thumbnail = session.scalar(
            select(Derivative)
            .join(CatalogAsset)
            .where(CatalogAsset.asset_id == PORTRAIT, Derivative.kind == "THUMBNAIL")
        )
        assert thumbnail is not None
        thumbnail.status = "READY"
        thumbnail.rel_path = "../outside.jpg"
        session.commit()
    assert client.get(f"/api/catalog/assets/{PORTRAIT}/thumbnail").status_code == 404


def test_symlink_escape_is_not_served(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
    tmp_path: Path,
) -> None:
    client, _, settings = catalog
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(THUMB_BYTES)
    link = settings.derivatives_root / PORTRAIT[:2] / PORTRAIT / "grid-v1.jpg"
    link.unlink()
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this host")
    assert client.get(f"/api/catalog/assets/{PORTRAIT}/thumbnail").status_code == 404


def test_thumbnail_has_private_cache_and_etag(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, _ = catalog
    url = f"/api/catalog/assets/{PHOTO}/thumbnail"
    response = client.get(url)
    assert response.status_code == 200
    assert response.content == THUMB_BYTES
    assert response.headers["content-type"].startswith("image/jpeg")
    assert "private" in response.headers["cache-control"]
    assert "etag" in response.headers
    cached = client.get(url, headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304
    assert cached.content == b""


@pytest.mark.parametrize(
    ("range_header", "status", "payload", "content_range"),
    [
        ("bytes=2-5", 206, b"2345", "bytes 2-5/10"),
        ("bytes=7-", 206, b"789", "bytes 7-9/10"),
        ("bytes=-3", 206, b"789", "bytes 7-9/10"),
        ("bytes=9-20", 206, b"9", "bytes 9-9/10"),
        ("bytes=20-", 416, b"", "bytes */10"),
        ("bytes=5-2", 416, b"", "bytes */10"),
        ("bytes=0-1,4-5", 416, b"", "bytes */10"),
    ],
)
def test_proxy_byte_ranges_support_seek(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
    range_header: str,
    status: int,
    payload: bytes,
    content_range: str,
) -> None:
    client, _, _ = catalog
    response = client.get(
        f"/api/catalog/assets/{PORTRAIT}/proxy", headers={"Range": range_header}
    )
    assert response.status_code == status
    assert response.content == payload
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == content_range
    if status == 206:
        assert response.headers["content-length"] == str(len(payload))
        assert response.headers["content-type"].startswith("video/mp4")


def test_proxy_full_response_and_gallery_navigation(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, _ = catalog
    proxy = client.get(f"/api/catalog/assets/{PORTRAIT}/proxy")
    assert proxy.status_code == 200
    assert proxy.content == PROXY_BYTES
    assert proxy.headers["accept-ranges"] == "bytes"

    trips = client.get("/gallery")
    assert trips.status_code == 200
    assert f"/gallery/{TRIP}" in trips.text
    gallery = client.get(f"/gallery/{TRIP}")
    assert gallery.status_code == 200
    assert gallery.text.count("/thumbnail") >= 3
    assert "INSTAGRAM_9X16" in gallery.text
    assert "Praia" in gallery.text
    assert "orbit" in gallery.text
    assert "yes" in gallery.text
    assert "00:12" in gallery.text
    assert '<select name="classification">' in gallery.text
    filtered = client.get(f"/gallery/{TRIP}?classification=INSTAGRAM_9X16")
    assert filtered.status_code == 200
    assert "1 de 3 assets" in filtered.text
    assert '<option value="INSTAGRAM_9X16" selected>' in filtered.text
    detail = client.get(f"/gallery/{TRIP}/assets/{PORTRAIT}")
    assert detail.status_code == 200
    assert "<video" in detail.text
    assert "playsinline" in detail.text
    assert f"/api/catalog/assets/{PORTRAIT}/proxy" in detail.text
    assert 'class="player-frame portrait"' in detail.text
    assert f'href="/gallery/{TRIP}"' in detail.text


def test_proxy_rejects_oversized_range_number(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, _ = catalog
    response = client.get(
        f"/api/catalog/assets/{PORTRAIT}/proxy",
        headers={"Range": "bytes=" + "9" * 5000 + "-"},
    )
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */10"


def test_ready_derivative_with_empty_file_is_not_served(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, sessions, settings = catalog
    path = settings.derivatives_root / PORTRAIT[:2] / PORTRAIT / "web-720p-v1.mp4"
    path.write_bytes(b"")
    with sessions() as session:
        derivative = session.scalar(
            select(Derivative)
            .join(CatalogAsset)
            .where(CatalogAsset.asset_id == PORTRAIT, Derivative.kind == "PROXY")
        )
        assert derivative is not None
        derivative.size_bytes = 0
        session.commit()
    assert client.get(f"/api/catalog/assets/{PORTRAIT}/proxy").status_code == 404


def test_unicode_editorial_filters_match_visible_values(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, sessions, _ = catalog
    with sessions() as session:
        asset = session.scalar(
            select(CatalogAsset).where(CatalogAsset.asset_id == PORTRAIT)
        )
        assert asset is not None
        asset.poi_final = "\u00c9vora"
        asset.movement = "A\u00e7\u00e3o"
        asset.people = "N\u00e3o"
        session.commit()
    for field, value in (
        ("poi", "\u00c9vora"),
        ("poi", "\u00e9vora"),
        ("movement", "a\u00e7\u00e3o"),
        ("people", "n\u00e3o"),
    ):
        response = client.get(
            f"/api/catalog/trips/{TRIP}/assets", params={field: value}
        )
        assert response.status_code == 200
        assert [item["asset_id"] for item in response.json()["assets"]] == [PORTRAIT]
    gallery = client.get(f"/gallery/{TRIP}", params={"poi": "\u00c9vora"})
    assert "1 de 3 assets" in gallery.text


def test_suggested_poi_filters_when_final_poi_is_empty(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, sessions, _ = catalog
    with sessions() as session:
        asset = session.scalar(
            select(CatalogAsset).where(CatalogAsset.asset_id == PORTRAIT)
        )
        assert asset is not None
        asset.poi_final = ""
        asset.poi_suggested = "\u00c9vora"
        session.commit()
    response = client.get(
        f"/api/catalog/trips/{TRIP}/assets", params={"poi": "\u00c9vora"}
    )
    assert [item["asset_id"] for item in response.json()["assets"]] == [PORTRAIT]


def test_if_range_date_cannot_bypass_single_range_validation(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, _ = catalog
    url = f"/api/catalog/assets/{PORTRAIT}/proxy"
    last_modified = client.get(url).headers["last-modified"]
    response = client.get(
        url,
        headers={
            "Range": "bytes=0-1,4-5",
            "If-Range": last_modified,
        },
    )
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */10"


def test_missing_ready_file_is_not_advertised_in_catalog_or_gallery(
    catalog: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, settings = catalog
    path = settings.derivatives_root / PHOTO[:2] / PHOTO / "grid-v1.jpg"
    path.unlink()
    detail = client.get(f"/api/catalog/assets/{PHOTO}")
    assert detail.status_code == 200
    assert detail.json()["thumbnail_url"] is None
    gallery = client.get(f"/gallery/{TRIP}")
    assert gallery.status_code == 200
    assert "Pr\u00e9via indispon\u00edvel" in gallery.text
