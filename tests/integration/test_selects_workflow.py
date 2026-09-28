"""Select generation, human decisions and original-only export."""

import hashlib
import json
import re
from pathlib import Path

import pytest
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
from drone_media_manager.db.models.core import Job
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory


def test_selects_review_and_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from drone_media_manager.selects.models import SelectCandidate
    from drone_media_manager.selects.repository import enqueue_export, interrupt_jobs

    settings = ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=tmp_path / "omv",
        selects_root=tmp_path / "output",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    source_dir = settings.omv_root / "trip"
    source_dir.mkdir(parents=True)
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with sessions() as session, session.begin():
        trip = Trip(name="Trip", slug="trip", nas_rel_path="trip")
        session.add_all(
            [
                trip,
                User(
                    username="editor", password_hash=hash_password("valid password 123")
                ),
            ]
        )
        session.flush()
        ids = []
        for n in range(2):
            path = source_dir / f"clip{n}.mp4"
            path.write_bytes(f"original-{n}".encode())
            asset = CatalogAsset(
                asset_id=f"{n:064x}",
                trip_id=trip.id,
                media_type="VIDEO",
                classification="YOUTUBE_16X9",
                verification_status="VERIFIED",
                duration_ms=10000,
            )
            session.add(asset)
            session.flush()
            ids.append(asset.id)
            session.add(
                AssetFile(
                    catalog_asset_id=asset.id,
                    role="ORIGINAL",
                    rel_path=f"trip/clip{n}.mp4",
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    size_bytes=path.stat().st_size,
                    availability_status="AVAILABLE",
                )
            )
        trip_id = trip.id
    client = TestClient(create_app(settings, sessions), base_url="https://testserver")
    base = f"/api/editorial/trips/{trip_id}/selects"
    assert client.get(base).status_code == 401
    page = client.get("/login")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    client.post(
        "/login",
        data={
            "username": "editor",
            "password": "valid password 123",
            "csrf_token": csrf,
        },
        headers={"Origin": "https://testserver"},
    )
    with sessions() as session:
        token = session.scalar(select(UserSession)).csrf_token
    headers = {"X-CSRF-Token": token, "Origin": "https://testserver"}
    assert client.post(base).status_code == 403
    assert client.post(base, headers=headers).json()["candidate_count"] == 2
    candidates = client.get(base).json()["candidates"]
    assert len(candidates) == 2 and all(
        not c["suggested"] and c["status"] == "PENDING" for c in candidates
    )
    first, second = candidates
    review_url = f"/api/editorial/selects/{first['id']}"
    assert (
        client.patch(
            review_url,
            json={"status": "INCLUDE", "start_ms": 1000, "end_ms": 5000},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.patch(
            review_url,
            json={"status": "INCLUDE", "start_ms": 9000, "end_ms": 11000},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/editorial/selects/{second['id']}",
            json={"status": "REJECT"},
            headers=headers,
        ).status_code
        == 200
    )
    assert client.post(base, headers=headers).json()["candidate_count"] == 2
    after = {c["id"]: c for c in client.get(base).json()["candidates"]}
    assert (
        after[first["id"]]["status"] == "INCLUDE"
        and after[first["id"]]["start_ms"] == 1000
    )
    assert after[second["id"]]["status"] == "REJECT"

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        Path(args[-1]).write_bytes(b"cut-video")
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(
        "drone_media_manager.selects.repository.subprocess.run", fake_run
    )
    response = client.post(
        base + "/exports", json={"mode": "ACCURATE"}, headers=headers
    )
    assert response.status_code == 202
    job = client.get(
        f"/api/editorial/select-export-jobs/{response.json()['id']}"
    ).json()
    assert job["status"] == "COMPLETE", (job, calls)
    assert (
        calls
        and "libx264" in calls[0]
        and calls[0][calls[0].index("-i") + 1] == str(source_dir / "clip0.mp4")
    )
    folder = Path(job["folder"])
    assert folder.is_relative_to(settings.selects_root)
    manifest = json.loads(
        (folder / "selects_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["mode"] == "ACCURATE" and manifest["selects"][0]["start_ms"] == 1000
    assert (folder / "selects.csv").is_file() and len(
        list((folder / "SELECTS").iterdir())
    ) == 1
    assert (source_dir / "clip0.mp4").read_bytes() == b"original-0"
    assert (source_dir / "clip1.mp4").read_bytes() == b"original-1"

    # Whole-file FAST export copies the verified original without invoking ffmpeg.
    assert (
        client.patch(
            review_url,
            json={"status": "INCLUDE", "start_ms": -1, "end_ms": -1},
            headers=headers,
        ).status_code
        == 200
    )
    whole_id = client.post(
        base + "/exports", json={"mode": "FAST"}, headers=headers
    ).json()["id"]
    whole = client.get(f"/api/editorial/select-export-jobs/{whole_id}").json()
    assert whole["status"] == "COMPLETE" and len(calls) == 1
    assert (
        Path(whole["folder"]) / "SELECTS" / "001_clip0.mp4"
    ).read_bytes() == b"original-0"

    # A cataloged SHA mismatch aborts without publishing another folder.
    assert (
        client.patch(
            review_url, json={"status": "INCLUDE"}, headers=headers
        ).status_code
        == 200
    )
    (source_dir / "clip0.mp4").write_bytes(b"changed")
    failed = client.post(
        base + "/exports", json={"mode": "FAST"}, headers=headers
    ).json()["id"]
    assert (
        client.get(f"/api/editorial/select-export-jobs/{failed}").json()["status"]
        == "FAILED"
    )
    assert len(list(settings.selects_root.iterdir())) == 2
    with sessions() as session:
        assert len(session.scalars(select(SelectCandidate)).all()) == 2
        assert session.get(Job, failed).error == "select_export_failed"
    # Restart does not change a confirmed review.
    with sessions() as session:
        pending = enqueue_export(session, trip_id, "FAST").id
    interrupt_jobs(sessions)
    with sessions() as session:
        assert session.get(Job, pending).status == "INTERRUPTED"
        assert session.get(SelectCandidate, first["id"]).status == "INCLUDE"
    engine.dispose()
