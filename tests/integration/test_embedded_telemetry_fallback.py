"""Clips without SRT use the MP4 ``djmd`` track for grouping and movement."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.grouping.embedded import EMBEDDED_PARSER_VERSION
from drone_media_manager.grouping.models import TelemetryTrack
from drone_media_manager.grouping.repository import (
    analyze_trip,
    ordered_assets,
    range_center,
)
from drone_media_manager.grouping.telemetry import TelemetrySample
from drone_media_manager.movement.repository import analyze_asset

# Two clips at the Cristo de Caconde, one 2 km away at the dam.
TRACKS = {
    "DJI_20260604171420_0223_D.MP4": (-21.5223, -46.6445),
    "DJI_20260604171556_0224_D.MP4": (-21.5224, -46.6446),
    "DJI_20260605102136_0228_D.MP4": (-21.5400, -46.6300),
}


def _track(lat: float, lon: float) -> list[TelemetrySample]:
    return [
        TelemetrySample(i * 1000, (i + 1) * 1000, lat, lon + i * 1e-6, 10.0)
        for i in range(10)
    ]


def _catalog(tmp_path: Path) -> tuple[ServerSettings, Session, str]:
    settings = ServerSettings(
        database_path=tmp_path / "catalog.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    settings.omv_root.mkdir()
    command.upgrade(alembic_config(settings), "head")
    session = session_factory(create_engine_from_settings(settings))()
    trip = Trip(name="Caconde", slug="caconde", nas_rel_path="caconde")
    session.add(trip)
    session.flush()
    start = datetime(2026, 6, 4, 17, 14, 20, tzinfo=UTC)
    for number, name in enumerate(TRACKS):
        asset = CatalogAsset(
            asset_id=f"{number + 1:064x}",
            trip_id=trip.id,
            media_type="VIDEO",
            classification="YOUTUBE_16X9",
            verification_status="VERIFIED",
            duration_ms=10000,
            capture_date=start.date().isoformat(),
            capture_time=(start + timedelta(minutes=2 * number)).isoformat(),
            capture_date_source="mp4_creation_time",
        )
        session.add(asset)
        session.flush()
        session.add(
            AssetFile(
                catalog_asset_id=asset.id,
                role="ORIGINAL",
                rel_path=f"caconde/{name}",
                sha256=f"{number + 1:x}" * 64,
                availability_status="AVAILABLE",
            )
        )
    session.commit()
    return settings, session, trip.id


def test_grouping_uses_embedded_gps_when_srt_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[str] = []

    def fake_reader(path: Path) -> list[TelemetrySample]:
        reads.append(path.name)
        return _track(*TRACKS[path.name])

    monkeypatch.setattr(
        "drone_media_manager.grouping.repository.read_embedded_samples", fake_reader
    )
    settings, session, trip_id = _catalog(tmp_path)

    suggestions = analyze_trip(session, settings, trip_id)
    session.commit()

    assets = ordered_assets(session, trip_id)
    assert [(s.start_asset_id, s.end_asset_id) for s in suggestions] == [
        (assets[0].id, assets[1].id),
        (assets[2].id, assets[2].id),
    ]
    tracks = session.scalars(select(TelemetryTrack)).all()
    assert {t.parser_version for t in tracks} == {EMBEDDED_PARSER_VERSION}
    first = session.scalar(
        select(TelemetryTrack).where(TelemetryTrack.catalog_asset_id == assets[0].id)
    )
    assert first is not None and first.sample_count == 10
    assert first.start_time is not None and first.end_time is not None
    assert first.end_time - first.start_time == timedelta(seconds=10)
    center = range_center(session, trip_id, assets[0].id, assets[1].id)
    assert center is not None and abs(center[0] - -21.52235) < 1e-6

    analyze_trip(session, settings, trip_id)  # Cached: no second MP4 read.
    assert len(reads) == 3
    session.close()


def test_failed_embedded_read_is_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "drone_media_manager.grouping.repository.read_embedded_samples",
        lambda _: [],
    )
    settings, session, trip_id = _catalog(tmp_path)

    analyze_trip(session, settings, trip_id)
    session.commit()

    assert session.scalars(select(TelemetryTrack)).all() == []
    session.close()


def test_movement_uses_embedded_track_and_records_its_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Path] = []

    def fake_reader(path: Path) -> list[TelemetrySample]:
        calls.append(path)
        return _track(*TRACKS[path.name])

    monkeypatch.setattr(
        "drone_media_manager.movement.repository.read_embedded_samples", fake_reader
    )
    settings, session, trip_id = _catalog(tmp_path)
    asset = ordered_assets(session, trip_id)[0]

    first = analyze_asset(session, settings, asset.id)
    session.commit()
    second = analyze_asset(session, settings, asset.id)
    session.commit()

    assert first.parser_version == EMBEDDED_PARSER_VERSION
    assert first.source_sha256 == "1" * 64
    assert first.samples_json != "[]"
    assert "no_usable_srt" not in first.evidence_json
    assert second.samples_json == first.samples_json
    assert len(calls) == 1  # Second analysis reuses the stored samples.
    session.close()
