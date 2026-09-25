"""Movement suggestions remain separate from final choices, including offline."""

import hashlib
import json
from pathlib import Path

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import select

from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset
from drone_media_manager.db.models.core import AuditEvent, Job
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.movement.models import MovementAnalysis, MovementReview
from drone_media_manager.movement.repository import (
    analyze_asset,
    enqueue_job,
    interrupt_jobs,
    review_movement,
    run_job,
)


def test_reprocessing_preserves_whole_and_segment_choices_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "catalog.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    settings.omv_root.mkdir()
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    content = "\n\n".join(
        f"{i + 1}\n00:00:{i:02},000 --> 00:00:{i + 1:02},000\n[latitude: 0] [longitude: 0] [rel_alt: 10] [yaw: {i * 8}] [gimbal_pitch: 0]"
        for i in range(10)
    )
    srt = settings.omv_root / "clip.srt"
    srt.write_text(content, encoding="utf-8")
    with sessions() as session:
        trip = Trip(name="Offline", slug="offline", nas_rel_path="offline")
        session.add(trip)
        session.flush()
        asset = CatalogAsset(
            asset_id="a" * 64,
            trip_id=trip.id,
            media_type="VIDEO",
            classification="YOUTUBE_16X9",
            verification_status="VERIFIED",
            duration_ms=10000,
        )
        session.add(asset)
        session.flush()
        session.add_all(
            [
                AssetFile(
                    catalog_asset_id=asset.id,
                    role="ORIGINAL",
                    rel_path="clip.mp4",
                    sha256="b" * 64,
                    availability_status="AVAILABLE",
                ),
                AssetFile(
                    catalog_asset_id=asset.id,
                    role="SRT",
                    rel_path="clip.srt",
                    sha256=hashlib.sha256(srt.read_bytes()).hexdigest(),
                    availability_status="AVAILABLE",
                ),
            ]
        )
        session.commit()
        asset_id, trip_id = asset.id, trip.id
        first = analyze_asset(session, settings, asset_id)
        assert first.value == "PAN"
        assert asset.movement is None
        review_movement(session, asset_id, "ORBITA", actor="editor")
        review_movement(
            session, asset_id, "PAN", actor="editor", start_ms=1000, end_ms=5000
        )
        session.commit()
    srt.unlink()  # A locally cached track remains usable with NAS offline.
    with sessions() as session:
        second = analyze_asset(session, settings, asset_id)
        session.commit()
        assert second.value == "PAN"
        assert session.get(CatalogAsset, asset_id).movement == "ORBITA"
        assert len(session.scalars(select(MovementAnalysis)).all()) == 2
        assert len(session.scalars(select(MovementReview)).all()) == 2
        assert len(session.scalars(select(AuditEvent)).all()) == 2
        reviews = session.scalars(select(MovementReview)).all()
        assert all(
            r.locked and r.actor == "editor" and r.source == "HUMAN" for r in reviews
        )
        srt_row = session.scalar(select(AssetFile).where(AssetFile.role == "SRT"))
        session.delete(srt_row)
        session.commit()
    with sessions() as session:
        job = enqueue_job(session, trip_id)
        job_id = job.id
    run_job(sessions, settings, job_id)
    with sessions() as session:
        assert session.get(Job, job_id).status == "COMPLETE"
        assert session.get(Job, job_id).progress == 1
        latest = session.scalar(
            select(MovementAnalysis).where(MovementAnalysis.superseded_at.is_(None))
        )
        assert latest.value == "UNKNOWN"
        assert json.loads(latest.evidence_json)["reason"] == "no_usable_srt"
        assert session.get(CatalogAsset, asset_id).movement == "ORBITA"
    with sessions() as session:
        pending_id = enqueue_job(session, trip_id).id
    with sessions() as session:
        assert enqueue_job(session, trip_id).id == pending_id
    interrupt_jobs(sessions)
    with sessions() as session:
        assert session.get(Job, pending_id).status == "INTERRUPTED"
        session.commit()
        failed_id = enqueue_job(session, trip_id).id

    def fail(*args: object) -> None:
        raise RuntimeError("private path and secret must not reach the response")

    monkeypatch.setattr("drone_media_manager.movement.repository.analyze_asset", fail)
    run_job(sessions, settings, failed_id)
    with sessions() as session:
        failed = session.get(Job, failed_id)
        assert failed.status == "FAILED"
        assert failed.error == "movement_analysis_failed"
        assert json.loads(failed.payload_json)["finished_at"]
        assert session.get(CatalogAsset, asset_id).movement == "ORBITA"
    engine.dispose()
