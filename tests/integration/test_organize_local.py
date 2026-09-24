from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from pydantic import SecretStr

from drone_media_manager.catalog.importer import import_manifest
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.organize import apply_plan, build_plan


def _probe(path: Path, ffprobe: str = "ffprobe") -> dict[str, object]:
    rotated = path.stem == "vertical"
    return {
        "codec": "h264",
        "duration_ms": 1000,
        "fps": 30.0,
        "encoded_width": 3840,
        "encoded_height": 2160,
        "rotation_degrees": 90 if rotated else 0,
        "display_matrix": "matrix" if rotated else None,
        "display_width": 2160 if rotated else 3840,
        "display_height": 3840 if rotated else 2160,
    }


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "DJI_001.MP4").write_bytes(b"video-one")
    (source / "DJI_001.SRT").write_bytes(b"telemetry")
    (source / "vertical.mp4").write_bytes(b"video-two")
    (source / "photo.JPEG").write_bytes(b"photo")
    (source / "orphan.srt").write_bytes(b"orphan")
    (source / "raw.dng").write_bytes(b"raw")
    return source


def test_plan_and_apply_keep_sidecar_and_source_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("drone_media_manager.organize.probe_video", _probe)
    source = _source(tmp_path)
    omv = tmp_path / "omv"
    omv.mkdir()
    before = {p.name: p.read_bytes() for p in source.iterdir()}

    plan = build_plan(
        source,
        omv,
        "Fernando de Noronha",
        "Baia dos Porcos",
        movement="orbita",
        people="sim",
        capture_date="2026-09-14",
    )
    preview = plan.preview()
    assert not (omv / "fernando-de-noronha").exists()
    assert len(preview["assets"]) == 3
    assert preview["orphan_srt"] == ["orphan.srt"]
    assert preview["unsupported"] == ["raw.dng"]
    assert {asset["classification"] for asset in preview["assets"]} == {
        "YOUTUBE_16X9",
        "INSTAGRAM_9X16",
        "FOTOS",
    }
    paired = next(a for a in preview["assets"] if a["source"]["srt_status"] == "paired")
    assert (
        Path(paired["output"]["video_relative_path"]).stem
        == Path(paired["output"]["srt_relative_path"]).stem
    )
    assert paired["editorial"]["capture_date_source"] == "user"

    first = apply_plan(plan)
    assert first["status"] == "APPLIED"
    assert first["counts"]["CREATED"] == 4
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    manifest = json.loads((omv / "fernando-de-noronha" / "MANIFESTO.json").read_text())
    assert len(manifest["assets"]) == 3
    assert manifest["assets"][0]["output"]["sha256"]
    assert (omv / paired["output"]["srt_relative_path"]).read_bytes() == b"telemetry"

    second = apply_plan(
        build_plan(
            source,
            omv,
            "Fernando de Noronha",
            "Baia dos Porcos",
            movement="orbita",
            people="sim",
            capture_date="2026-09-14",
        )
    )
    assert second["status"] == "APPLIED"
    assert second["counts"]["CREATED"] == 0
    assert second["counts"]["ALREADY_OK"] == 4


def test_conflicting_destination_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("drone_media_manager.organize.probe_video", _probe)
    source = _source(tmp_path)
    omv = tmp_path / "omv"
    omv.mkdir()
    plan = build_plan(source, omv, "Trip", "Place")
    target = omv / plan.preview()["assets"][0]["output"]["video_relative_path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"different")

    result = apply_plan(plan)
    assert result["status"] == "CONFLICT"
    assert target.read_bytes() == b"different"
    assert not (omv / "trip" / "MANIFESTO.json").exists()


@pytest.mark.parametrize(
    "existing",
    [
        ["invalid"],
        {"schema_version": 1, "trip": {"slug": "trip", "name": "Trip!"}, "assets": []},
        {
            "schema_version": 1,
            "trip": {"slug": "trip", "name": "Trip"},
            "assets": [{"asset_id": "bad"}],
        },
    ],
)
def test_existing_manifest_conflict_is_preserved(
    tmp_path: Path, existing: object
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "photo.jpg").write_bytes(b"photo")
    omv = tmp_path / "omv"
    manifest = omv / "trip" / "MANIFESTO.json"
    manifest.parent.mkdir(parents=True)
    original = json.dumps(existing)
    manifest.write_text(original)

    result = apply_plan(build_plan(source, omv, "Trip", "Place"))
    assert result["status"] == "CONFLICT"
    assert manifest.read_text() == original


def test_edited_tags_do_not_change_asset_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("drone_media_manager.organize.probe_video", _probe)
    source = _source(tmp_path)
    omv = tmp_path / "omv"
    original = build_plan(source, omv, "Trip", "First Place").preview()
    edited = build_plan(source, omv, "Trip", "Second Place").preview()
    assert [a["asset_id"] for a in original["assets"]] == [
        a["asset_id"] for a in edited["assets"]
    ]
    assert [a["output"] for a in original["assets"]] != [
        a["output"] for a in edited["assets"]
    ]


def test_capture_date_comes_from_mp4_metadata_without_manual_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dated_probe(path: Path, ffprobe: str = "ffprobe") -> dict[str, object]:
        return {**_probe(path, ffprobe), "creation_time": "2026-09-14T10:59:56Z"}

    monkeypatch.setattr("drone_media_manager.organize.probe_video", dated_probe)
    source = _source(tmp_path)
    omv = tmp_path / "omv"
    plan = build_plan(source, omv, "Trip", "Place")
    videos = [a for a in plan.preview()["assets"] if a["video"] is not None]
    assert all(a["editorial"]["capture_date"] == "2026-09-14" for a in videos)
    assert all(
        a["editorial"]["capture_date_source"] == "mp4_creation_time" for a in videos
    )


def test_dji_photo_filename_supplies_date_with_recorded_source(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "DJI_20260918130837_0119_D.JPG").write_bytes(b"photo")
    omv = tmp_path / "omv"
    omv.mkdir()
    asset = build_plan(source, omv, "Trip", "Place").preview()["assets"][0]
    assert asset["editorial"]["capture_date"] == "2026-09-18"
    assert asset["editorial"]["capture_date_source"] == "dji_filename"
    assert Path(asset["output"]["photo_relative_path"]).name.startswith("2026-09-18_")


def test_organizer_manifest_imports_into_mac_catalog(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "DJI_20260918130837_0119_D.JPG").write_bytes(b"photo")
    omv = tmp_path / "omv"
    omv.mkdir()
    result = apply_plan(build_plan(source, omv, "Viagem", "Praia"))
    assert result["status"] == "APPLIED"

    settings = ServerSettings(
        database_path=tmp_path / "catalog.sqlite3",
        omv_root=omv,
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    try:
        with session_factory(engine)() as session:
            report = import_manifest(
                session, omv, Path(result["manifest"]), verify_hash=True
            )
            assert (report.created_assets, report.created_files, report.conflicts) == (
                1,
                1,
                0,
            )
    finally:
        engine.dispose()


def test_new_trip_uses_neutral_names_and_keeps_pair_and_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("drone_media_manager.organize.probe_video", _probe)
    source = _source(tmp_path)
    (source / ("Inválido espaço " + "x" * 90 + ".jpg")).write_bytes(b"long-photo")
    omv = tmp_path / "omv"
    omv.mkdir()
    plan = build_plan(source, omv, "Nova viagem")
    preview = plan.preview()["manifest_preview"]
    assert preview["naming_scheme"] == "neutral-v1"
    assert all(asset["location"]["poi_final"] is None for asset in preview["assets"])
    assert all(asset["editorial"]["movement"] is None for asset in preview["assets"])
    assert all(asset["editorial"]["people"] is None for asset in preview["assets"])
    for asset in preview["assets"]:
        paths = asset["output"]
        relative = paths["video_relative_path"] or paths["photo_relative_path"]
        assert relative is not None and "/a-classificar/" in relative
        assert "desconhecido" not in Path(relative).name
        assert len(Path(relative).stem.split("_")[1]) <= 48
        if paths["srt_relative_path"]:
            assert Path(paths["srt_relative_path"]).stem == Path(relative).stem
    first = apply_plan(plan)
    assert first["status"] == "APPLIED"
    manifest_path = Path(first["manifest"])
    before = manifest_path.read_bytes()
    assert apply_plan(build_plan(source, omv, "Nova viagem"))["counts"]["CREATED"] == 0
    assert manifest_path.read_bytes() == before
    assert (
        apply_plan(build_plan(source, omv, "Nova viagem", movement="orbita"))["counts"][
            "CREATED"
        ]
        == 0
    )
    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert all(
        asset["editorial"]["movement"] == "orbita"
        for asset in updated["assets"]
        if asset["video"] is not None
    )


def test_existing_legacy_manifest_replays_without_renaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("drone_media_manager.organize.probe_video", _probe)
    source = _source(tmp_path)
    omv = tmp_path / "omv"
    omv.mkdir()
    original_scheme = __import__(
        "drone_media_manager.organize", fromlist=["_naming_scheme"]
    )._naming_scheme
    monkeypatch.setattr(
        "drone_media_manager.organize._naming_scheme", lambda path: None
    )
    first = apply_plan(
        build_plan(
            source, omv, "Viagem legada", "Praia", movement="orbita", people="sim"
        )
    )
    monkeypatch.setattr("drone_media_manager.organize._naming_scheme", original_scheme)
    assert first["status"] == "APPLIED"
    manifest_path = Path(first["manifest"])
    legacy = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy.pop("naming_scheme", None)
    legacy["assets"].sort(key=lambda asset: asset["classification"] != "FOTOS")
    manifest_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    before = manifest_path.read_bytes()
    plan = build_plan(source, omv, "Viagem legada")
    assert plan.preview()["manifest_preview"].get("naming_scheme") is None
    result = apply_plan(plan)
    assert result["status"] == "APPLIED"
    assert result["counts"] == {"CREATED": 0, "ALREADY_OK": 4}
    assert manifest_path.read_bytes() == before
