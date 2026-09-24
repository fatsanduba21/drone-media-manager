"""Original-only downloads as separate files, with a validated batch list."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from drone_media_manager.api.app import create_app
from drone_media_manager.auth.passwords import hash_password
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.auth import User, UserSession
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset, Derivative
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory

A, B, C, OTHER = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
BYTES = {
    A: b"original-video-A",
    B: b"original-video-B",
    C: b"original-photo-C",
    OTHER: b"other-trip-video",
}


@pytest.fixture
def downloads(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, sessionmaker[Session], ServerSettings]]:
    omv = tmp_path / "omv"
    omv.mkdir()
    settings = ServerSettings(
        database_path=tmp_path / "downloads.sqlite3",
        omv_root=omv,
        derivatives_root=tmp_path / "cache",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with sessions() as session:
        trip = Trip(name="Viagem", slug="viagem", nas_rel_path="viagem")
        other_trip = Trip(name="Outra", slug="outra", nas_rel_path="outra")
        session.add_all(
            [
                trip,
                other_trip,
                User(
                    username="editor",
                    password_hash=hash_password("correct horse battery staple"),
                ),
            ]
        )
        session.flush()
        rows = (
            (A, trip.id, "VIDEO", "viagem/poi-a/YOUTUBE_16x9/Céu.mp4"),
            (B, trip.id, "VIDEO", "viagem/poi-b/YOUTUBE_16x9/Céu.mp4"),
            (C, trip.id, "PHOTO", "viagem/fotos/FOTO_01.jpg"),
            (OTHER, other_trip.id, "VIDEO", "outra/poi/ORIGINAL.mp4"),
        )
        for asset_id, trip_id, media_type, rel_path in rows:
            asset = CatalogAsset(
                asset_id=asset_id,
                trip_id=trip_id,
                media_type=media_type,
                classification="FOTOS" if media_type == "PHOTO" else "YOUTUBE_16X9",
                verification_status="VERIFIED",
            )
            session.add(asset)
            session.flush()
            path = omv / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(BYTES[asset_id])
            session.add(
                AssetFile(
                    catalog_asset_id=asset.id,
                    role="ORIGINAL",
                    rel_path=rel_path,
                    sha256=hashlib.sha256(BYTES[asset_id]).hexdigest(),
                    size_bytes=len(BYTES[asset_id]),
                    availability_status="AVAILABLE",
                )
            )
            if asset_id == A:
                proxy = settings.derivatives_root / A[:2] / A / "web-720p-v1.mp4"
                proxy.parent.mkdir(parents=True, exist_ok=True)
                proxy.write_bytes(b"proxy-only")
                session.add(
                    Derivative(
                        catalog_asset_id=asset.id,
                        kind="PROXY",
                        status="READY",
                        profile_version="web-720p-v1",
                        source_sha256="f" * 64,
                        rel_path=f"{A[:2]}/{A}/web-720p-v1.mp4",
                        output_sha256=hashlib.sha256(b"proxy-only").hexdigest(),
                        size_bytes=10,
                    )
                )
        session.commit()
    with TestClient(
        create_app(settings, sessions), base_url="https://testserver"
    ) as client:
        page = client.get("/login")
        token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
        assert token is not None
        assert (
            client.post(
                "/login",
                data={
                    "username": "editor",
                    "password": "correct horse battery staple",
                    "csrf_token": token[1],
                },
                follow_redirects=False,
            ).status_code
            == 303
        )
        yield client, sessions, settings
    engine.dispose()


def _select(client: TestClient, sessions: sessionmaker[Session], asset_id: str) -> None:
    with sessions() as session:
        csrf = session.scalar(select(UserSession.csrf_token))
    assert csrf is not None
    response = client.put(
        f"/api/catalog/assets/{asset_id}/selection",
        json={"selected": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200


def test_individual_download_is_original_with_editorial_name(
    downloads: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, _, _ = downloads
    response = client.get(f"/api/catalog/assets/{A}/download")
    assert response.status_code == 200
    assert response.content == BYTES[A]
    assert response.content != b"proxy-only"
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.headers["content-disposition"].startswith("attachment;")
    assert 'filename="Ceu-aaaaaaaaaaaa.mp4"' in response.headers["content-disposition"]
    assert (
        "filename*=UTF-8''C%C3%A9u-aaaaaaaaaaaa.mp4"
        in response.headers["content-disposition"]
    )
    assert "\r" not in response.headers["content-disposition"]
    assert "\n" not in response.headers["content-disposition"]
    assert "C" in response.headers["content-disposition"]
    assert response.headers["content-length"] == str(len(BYTES[A]))


def test_selected_downloads_lists_exactly_trip_selection_without_zip(
    downloads: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, sessions, settings = downloads
    _select(client, sessions, A)
    _select(client, sessions, B)
    _select(client, sessions, OTHER)
    response = client.get("/api/catalog/trips/viagem/selected-downloads")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["total_size_bytes"] == len(BYTES[A]) + len(BYTES[B])
    assert [item["asset_id"] for item in body["files"]] == [A, B]
    assert len({item["filename"] for item in body["files"]}) == 2
    for item in body["files"]:
        assert client.get(item["url"]).content == BYTES[item["asset_id"]]
    assert str(settings.omv_root) not in response.text
    assert ".zip" not in response.text.lower()


def test_empty_selection_and_wrong_trip_are_clear(
    downloads: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, sessions, _ = downloads
    response = client.get("/api/catalog/trips/viagem/selected-downloads")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "selection_empty"
    _select(client, sessions, OTHER)
    assert client.get("/api/catalog/trips/viagem/selected-downloads").status_code == 409


@pytest.mark.parametrize(
    "invalid", ["missing", "status", "traversal", "absolute", "size", "srt_role"]
)
def test_invalid_original_blocks_single_and_batch_before_transfer(
    downloads: tuple[TestClient, sessionmaker[Session], ServerSettings],
    invalid: str,
) -> None:
    client, sessions, settings = downloads
    _select(client, sessions, A)
    with sessions() as session:
        original = session.scalar(
            select(AssetFile).join(CatalogAsset).where(CatalogAsset.asset_id == A)
        )
        assert original is not None
        if invalid == "missing":
            (settings.omv_root / original.rel_path).unlink()
        elif invalid == "status":
            original.availability_status = "MISSING"
        elif invalid == "traversal":
            original.rel_path = "../outside.mp4"
        elif invalid == "absolute":
            original.rel_path = "C:/outside.mp4"
        elif invalid == "size":
            original.size_bytes = 1
        else:
            original.role = "SRT"
        session.commit()
    assert client.get(f"/api/catalog/assets/{A}/download").status_code == 409
    response = client.get("/api/catalog/trips/viagem/selected-downloads")
    assert response.status_code == 409
    assert str(settings.omv_root) not in response.text


def test_symlink_escape_is_rejected(
    downloads: tuple[TestClient, sessionmaker[Session], ServerSettings],
    tmp_path: Path,
) -> None:
    client, sessions, settings = downloads
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(BYTES[A])
    path = settings.omv_root / "viagem/poi-a/YOUTUBE_16x9/Céu.mp4"
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation unavailable on this host")
    _select(client, sessions, A)
    assert client.get(f"/api/catalog/assets/{A}/download").status_code == 409
    assert client.get("/api/catalog/trips/viagem/selected-downloads").status_code == 409


def test_unsafe_editorial_filename_is_sanitized() -> None:
    from drone_media_manager.catalog.downloads import safe_filename

    name = safe_filename("  CON:bad\\name\r\n.mp4  ", A)
    assert "/" not in name and "\\" not in name
    assert "\r" not in name and "\n" not in name
    assert name.endswith(".mp4")


def test_gallery_offers_separate_batch_and_individual_original_links(
    downloads: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, sessions, _ = downloads
    _select(client, sessions, A)
    _select(client, sessions, B)
    page = client.get("/gallery/viagem")
    assert page.status_code == 200
    assert "Baixar selecionados" in page.text
    assert page.text.count("data-download-url=") == 2
    assert f"/api/catalog/assets/{A}/download" in page.text
    assert f"/api/catalog/assets/{B}/download" in page.text
    assert "Baixar original" in page.text
    assert ".zip" not in page.text.lower()
    detail = client.get(f"/gallery/viagem/assets/{A}")
    assert f"/api/catalog/assets/{A}/download" in detail.text


def test_unavailable_selection_does_not_offer_batch_button(
    downloads: tuple[TestClient, sessionmaker[Session], ServerSettings],
) -> None:
    client, sessions, settings = downloads
    _select(client, sessions, A)
    (settings.omv_root / "viagem/poi-a/YOUTUBE_16x9/Céu.mp4").unlink()
    page = client.get("/gallery/viagem")
    assert page.status_code == 200
    assert "Original indisponível" in page.text
    assert 'id="download-selected"' not in page.text


def test_unicode_only_name_keeps_extension_in_ascii_fallback() -> None:
    from drone_media_manager.api.routes.downloads import _content_disposition

    header = _content_disposition("空撮.mp4")
    assert 'filename="original.mp4"' in header
    assert "filename*=UTF-8''%E7%A9%BA%E6%92%AE.mp4" in header
