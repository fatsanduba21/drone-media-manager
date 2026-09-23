"""Derivatives are keyed by catalog identity and source content."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import select

from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset, Derivative
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.derivatives.service import generate_derivatives


class FakeRenderer:
    fail = False

    def render(self, source: Path, target: Path, kind: str) -> None:
        if self.fail:
            target.write_bytes(b"partial")
            raise RuntimeError("simulated conversion failure")
        target.write_bytes(b"valid-" + kind.encode())

    def valid(self, path: Path, kind: str) -> bool:
        return path.read_bytes() == b"valid-" + kind.encode()


def test_generate_reuse_and_regenerate_on_source_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    omv = tmp_path / "omv"
    omv.mkdir()
    source = omv / "a.jpg"
    source.write_bytes(b"source-one")
    settings = ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=omv,
        derivatives_root=tmp_path / "cache",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    with session_factory(engine)() as session:
        trip = Trip(name="Trip", slug="trip", nas_rel_path="trip")
        session.add(trip)
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
                rel_path="a.jpg",
                sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                availability_status="AVAILABLE",
            )
        )
        session.commit()

        renderer = FakeRenderer()
        first = generate_derivatives(session, settings, renderer=renderer)
        assert first.generated == 1 and first.reused == 0
        row = session.scalar(select(Derivative))
        assert row is not None and row.status == "READY"
        assert (settings.derivatives_root / row.rel_path).is_file()

        second = generate_derivatives(session, settings, renderer=renderer)
        assert second.generated == 0 and second.reused == 1

        source.write_bytes(b"source-two")
        third = generate_derivatives(session, settings, renderer=renderer)
        assert third.generated == 1 and third.reused == 0
        assert (
            session.scalar(select(Derivative)).source_sha256
            == hashlib.sha256(b"source-two").hexdigest()
        )

        cache_file = settings.derivatives_root / row.rel_path
        cache_file.write_bytes(b"corrupt")
        repaired = generate_derivatives(session, settings, renderer=renderer)
        assert repaired.generated == 1 and repaired.reused == 0

        from drone_media_manager.derivatives.service import PROFILES

        monkeypatch.setitem(PROFILES, "THUMBNAIL", "grid-v2")
        upgraded = generate_derivatives(session, settings, renderer=renderer)
        assert upgraded.generated == 1 and upgraded.reused == 0
        assert session.scalar(select(Derivative)).profile_version == "grid-v2"

        source.write_bytes(b"source-three")
        renderer.fail = True
        failed = generate_derivatives(session, settings, renderer=renderer)
        assert failed.failed == 1
        assert session.scalar(select(Derivative)).status == "ERROR"
        assert not list(cache_file.parent.glob(".dmm-*.tmp"))
    engine.dispose()


def test_derivatives_root_cannot_be_on_omv(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="Derivatives cache"):
        ServerSettings(
            database_path=tmp_path / "db.sqlite3",
            omv_root=tmp_path / "omv",
            derivatives_root=tmp_path / "omv" / "cache",
            worker_bootstrap_token=SecretStr("x" * 32),
        )


def test_photo_thumbnail_applies_exif_orientation(tmp_path: Path) -> None:
    from PIL import Image

    from drone_media_manager.derivatives.service import FFmpegRenderer

    source = tmp_path / "portrait.jpg"
    image = Image.new("RGB", (80, 40), "red")
    exif = Image.Exif()
    exif[274] = 6
    image.save(source, exif=exif)
    target = tmp_path / "thumb.tmp"
    renderer = FFmpegRenderer()
    renderer.render(source, target, "THUMBNAIL")
    assert renderer.valid(target, "THUMBNAIL")
    with Image.open(target) as thumbnail:
        assert thumbnail.size == (40, 80)
