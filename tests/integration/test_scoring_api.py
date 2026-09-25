"""Scoring jobs retain evidence and never mutate editorial choices or media."""

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from pydantic import SecretStr
from sqlalchemy import select

from drone_media_manager.api.app import create_app
from drone_media_manager.auth.passwords import hash_password
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.auth import User, UserSession
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset, Derivative
from drone_media_manager.db.models.core import AuditEvent, Job
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.editorial.models import EditorialField
from drone_media_manager.grouping.models import LocationGroup


def test_scores_api_history_profiles_context_and_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from drone_media_manager.scoring.repository import (
        enqueue_job,
        interrupt_jobs,
        run_job,
    )

    settings = ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=tmp_path / "offline",
        derivatives_root=tmp_path / "cache",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    settings.derivatives_root.mkdir()
    image = Image.new("RGB", (128, 128), "gray")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 90, 90), fill="white")
    thumb = settings.derivatives_root / "thumb.jpg"
    image.save(thumb)
    thumb_hash = hashlib.sha256(thumb.read_bytes()).hexdigest()
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with sessions() as session, session.begin():
        trip = Trip(name="Teste", slug="teste", nas_rel_path="teste")
        session.add_all(
            [
                trip,
                User(
                    username="editor", password_hash=hash_password("valid password 123")
                ),
            ]
        )
        session.flush()
        group = LocationGroup(
            trip_id=trip.id, name_final="Barco", name_source="HUMAN", name_locked=True
        )
        session.add(group)
        session.flush()
        ids = []
        for n in range(4):
            asset = CatalogAsset(
                asset_id=f"{n:064x}",
                trip_id=trip.id,
                location_group_id=group.id if n < 3 else None,
                media_type="VIDEO",
                classification="YOUTUBE_16X9",
                verification_status="VERIFIED",
                movement="ORBITA",
                people="YES",
                duration_ms=10000,
            )
            session.add(asset)
            session.flush()
            ids.append(asset.id)
            session.add_all(
                [
                    AssetFile(
                        catalog_asset_id=asset.id,
                        role="ORIGINAL",
                        rel_path=f"{n}.mp4",
                        sha256=f"{n:064x}",
                        availability_status="MISSING",
                    ),
                    EditorialField(
                        catalog_asset_id=asset.id,
                        kind="SUBJECT",
                        value="barco" if n != 2 else "praia",
                        actor="editor",
                    ),
                    Derivative(
                        catalog_asset_id=asset.id,
                        kind="THUMBNAIL",
                        status="READY",
                        profile_version="v1",
                        source_sha256=f"{n:064x}",
                        rel_path="thumb.jpg",
                        output_sha256=thumb_hash,
                    ),
                ]
            )
        trip_id = trip.id
    client = TestClient(create_app(settings, sessions), base_url="https://testserver")
    url = f"/api/editorial/trips/{trip_id}/scores"
    assert client.get(url).status_code == 401
    login = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', login.text)[1]
    client.post(
        "/login",
        data={
            "username": "editor",
            "password": "valid password 123",
            "csrf_token": token,
        },
        headers={"Origin": "https://testserver"},
    )
    with sessions() as session:
        csrf = session.scalar(select(UserSession)).csrf_token
    headers = {"X-CSRF-Token": csrf, "Origin": "https://testserver"}
    assert client.post(url, json={"profile": "instagram"}).status_code == 403
    assert client.get(url).json()["results"] == []
    profiles = client.get("/api/editorial/score-profiles").json()
    assert profiles["instagram"]["technical"] == 30
    # Two editors creating a profile must both succeed with a serial audit trail.
    import drone_media_manager.scoring.repository as scoring

    original_weights = scoring.profile_weights

    def delayed_weights(session, profile):
        result = original_weights(session, profile)
        time.sleep(0.1)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(scoring, "profile_weights", delayed_weights)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda weight: client.put(
                        "/api/editorial/score-profiles/youtube",
                        json={"weights": {"technical": weight}},
                        headers=headers,
                    ),
                    (40, 60),
                )
            )
        assert all(response.status_code == 200 for response in responses)
    with sessions() as session:
        events = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.action == "scoring.profile.update")
            .order_by(AuditEvent.occurred_at)
        ).all()
        assert (
            json.loads(events[1].details_json)["before"]
            == json.loads(events[0].details_json)["after"]
        )
    for weights in ({"technical": -1}, {"technical": 0}, {"bogus": 50}):
        assert (
            client.put(
                "/api/editorial/score-profiles/instagram",
                json={"weights": weights},
                headers=headers,
            ).status_code
            == 422
        )
    result = client.post(url, json={"profile": "instagram"}, headers=headers)
    assert result.status_code == 202
    first_id = result.json()["id"]
    first = client.get(url).json()
    assert first["status"] == "COMPLETE" and not first["stale"]
    rows = {row["asset_id"]: row for row in first["results"]}
    assert rows[ids[0]]["similar_takes"] == [{"asset_id": ids[1], "distance": 0}]
    assert rows[ids[2]]["similar_takes"] == rows[ids[3]]["similar_takes"] == []
    assert rows[ids[0]]["motion_score"] is None
    assert rows[ids[0]]["composition_score"] is None
    assert rows[ids[0]]["technical_score"] is not None
    assert rows[ids[0]]["coverage"] < 1
    assert (
        client.put(
            "/api/editorial/score-profiles/instagram",
            json={"weights": {"duration": 100}},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.get(url).json()["stale"]
    client.post(url, json={"profile": "instagram"}, headers=headers)
    assert all(
        row["editorial_score"] == 100 for row in client.get(url).json()["results"]
    )
    with sessions() as session, session.begin():
        session.get(CatalogAsset, ids[1]).movement = "PAN"
    assert client.get(url).json()["stale"]
    client.post(url, json={"profile": "instagram"}, headers=headers)
    assert all(not row["similar_takes"] for row in client.get(url).json()["results"])
    assert (
        client.get(f"/api/editorial/score-jobs/{first_id}").json()["weights"][
            "technical"
        ]
        == 30
    )
    settings.omv_root.mkdir()
    srt = settings.omv_root / "clip.srt"
    srt.write_text(
        "\n\n".join(
            f"{i + 1}\n00:00:0{i},000 --> 00:00:0{i + 1},000\n[yaw: {i}] [speed: 1]"
            for i in range(4)
        ),
        encoding="utf-8",
    )
    with sessions() as session, session.begin():
        session.add(
            AssetFile(
                catalog_asset_id=ids[0],
                role="SRT",
                rel_path="clip.srt",
                sha256=hashlib.sha256(srt.read_bytes()).hexdigest(),
                availability_status="AVAILABLE",
            )
        )
    client.post(url, json={"profile": "instagram"}, headers=headers)
    scored = {row["asset_id"]: row for row in client.get(url).json()["results"]}
    assert scored[ids[0]]["motion_score"] == 100
    assert scored[ids[1]]["motion_score"] is None
    assert (
        scored[ids[0]]["evidence"]["motion"]["source_sha256"]
        == hashlib.sha256(srt.read_bytes()).hexdigest()
    )
    # Invalid/outdated derivative paths cannot escape the configured cache.
    with sessions() as session, session.begin():
        for row in session.scalars(select(Derivative)):
            row.rel_path = "../outside.jpg"
    client.post(url, json={"profile": "youtube"}, headers=headers)
    assert all(
        row["technical_score"] is None
        for row in client.get(url + "?profile=youtube").json()["results"]
    )
    with sessions() as session:
        pending = enqueue_job(session, trip_id, "instagram").id
    with sessions() as session:
        assert enqueue_job(session, trip_id, "instagram").id == pending
    interrupt_jobs(sessions)
    with sessions() as session:
        assert session.get(Job, pending).status == "INTERRUPTED"
    with sessions() as session:
        failed = enqueue_job(session, trip_id, "instagram").id
    monkeypatch.setattr(
        "drone_media_manager.scoring.repository.score_asset",
        lambda *args: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    run_job(sessions, settings, failed)
    with sessions() as session:
        job = session.get(Job, failed)
        assert job.status == "FAILED" and job.error == "score_analysis_failed"
        assert json.loads(job.payload_json)["finished_at"]
        assert session.get(CatalogAsset, ids[0]).movement == "ORBITA"
        assert len(session.scalars(select(AssetFile)).all()) == 5
    assert hashlib.sha256(thumb.read_bytes()).hexdigest() == thumb_hash
    engine.dispose()
