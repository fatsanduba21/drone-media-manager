"""Phase 2A catalog behavior against a migrated SQLite database."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import func, select

from drone_media_manager.catalog.importer import (
    ManifestError,
    import_manifest,
    load_manifest,
    preview_manifest,
    resolve_omv_path,
)
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import (
    AssetFile,
    CatalogAsset,
    ManifestImport,
)
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory


def _asset(asset_id: str, classification: str = "FOTOS") -> dict[str, object]:
    video = classification != "FOTOS"
    rel = f"journey/poi/{'YOUTUBE_16x9' if video else 'FOTOS'}/{asset_id}.{'mp4' if video else 'jpg'}"
    return {
        "asset_id": asset_id,
        "classification": classification,
        "trip": {"name": "Journey", "slug": "journey", "external_id": None},
        "source": {"srt_status": "missing" if video else "not_applicable"},
        "video": {
            "codec": "h264",
            "duration_ms": 1000,
            "fps": 30.0,
            "encoded_width": 1920,
            "encoded_height": 1080,
            "display_width": 1920,
            "display_height": 1080,
            "rotation_degrees": None,
        }
        if video
        else None,
        "location": {"poi_final": "poi", "poi_suggested": None},
        "editorial": {
            "capture_date": None,
            "capture_date_source": "unknown",
            "movement": None,
            "people": None,
        },
        "output": {
            "video_relative_path": rel if video else None,
            "photo_relative_path": None if video else rel,
            "srt_relative_path": None,
            "sha256": "a" * 64,
            "srt_sha256": None,
            "verification_status": "VERIFIED",
        },
    }


def _setup(tmp_path: Path, assets: list[dict[str, object]]):
    root = tmp_path / "omv"
    root.mkdir()
    manifest = root / "journey" / "MANIFESTO.json"
    manifest.parent.mkdir()
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "trip": {"name": "Journey", "slug": "journey", "external_id": None},
                "assets": assets,
                "orphan_srt": [],
                "unsupported": [],
            }
        )
    )
    for asset in assets:
        output = asset["output"]
        assert isinstance(output, dict)
        for key in ("video_relative_path", "photo_relative_path", "srt_relative_path"):
            rel = output.get(key)
            if isinstance(rel, str):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"media")
    settings = ServerSettings(
        database_path=tmp_path / "test.sqlite3",
        omv_root=root,
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    return root, manifest, engine


def test_first_import_and_second_import_are_idempotent(tmp_path: Path) -> None:
    video = _asset("1" * 64, "YOUTUBE_16X9")
    output = video["output"]
    assert isinstance(output, dict)
    output["srt_relative_path"] = "journey/poi/YOUTUBE_16x9/video.srt"
    output["srt_sha256"] = "b" * 64
    source = video["source"]
    assert isinstance(source, dict)
    source["srt_status"] = "paired"
    root, manifest, engine = _setup(tmp_path, [video, _asset("2" * 64)])
    sessions = session_factory(engine)
    with sessions() as session:
        preview = preview_manifest(session, root, manifest)
        assert (preview.created_assets, preview.available_files) == (2, 3)
        assert session.scalar(select(func.count()).select_from(Trip)) == 0
        first = import_manifest(session, root, manifest)
        assert (first.created_assets, first.created_files, first.conflicts) == (2, 3, 0)
        second = import_manifest(session, root, manifest)
        assert (
            second.created_assets,
            second.created_files,
            second.already_imported,
        ) == (0, 0, 2)
        assert session.scalar(select(func.count()).select_from(Trip)) == 1
        assert session.scalar(select(func.count()).select_from(CatalogAsset)) == 2
        assert session.scalar(select(func.count()).select_from(AssetFile)) == 3
        assert session.scalar(select(func.count()).select_from(ManifestImport)) == 2
        assert session.scalar(select(Trip.nas_rel_path)) == "journey"
    engine.dispose()


def test_conflicts_duplicate_and_missing_file(tmp_path: Path) -> None:
    first = _asset("1" * 64)
    root, manifest, engine = _setup(tmp_path, [first])
    sessions = session_factory(engine)
    with sessions() as session:
        import_manifest(session, root, manifest)
        duplicate = _asset("2" * 64)
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "trip": {"name": "Journey", "slug": "journey"},
                    "assets": [first, duplicate],
                }
            )
        )
        report = import_manifest(session, root, manifest)
        assert report.possible_duplicates == 1
        assert report.missing_files == 1  # The new file was not created.
        assert session.scalar(select(func.count()).select_from(CatalogAsset)) == 2
        output = first["output"]
        assert isinstance(output, dict)
        output["sha256"] = "c" * 64
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "trip": {"name": "Journey", "slug": "journey"},
                    "assets": [first],
                }
            )
        )
        conflict = preview_manifest(session, root, manifest)
        assert conflict.conflicts == 1
        assert import_manifest(session, root, manifest).status == "CONFLICT"
        assert session.scalar(select(func.count()).select_from(CatalogAsset)) == 2
        first_trip = first["trip"]
        assert isinstance(first_trip, dict)
        first_trip["name"] = "Different"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "trip": {"name": "Different", "slug": "journey"},
                    "assets": [first],
                }
            )
        )
        assert preview_manifest(session, root, manifest).status == "CONFLICT"
    engine.dispose()


def test_reject_unsupported_schema_and_traversal(tmp_path: Path) -> None:
    asset = _asset("1" * 64)
    root, manifest, engine = _setup(tmp_path, [asset])
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "trip": {"name": "Journey", "slug": "journey"},
                "assets": [asset],
            }
        )
    )
    with pytest.raises(ManifestError, match="UNSUPPORTED_SCHEMA"):
        load_manifest(root, manifest)
    with pytest.raises(ManifestError, match="unsafe path"):
        resolve_omv_path(root, "../escape.jpg")
    output = asset["output"]
    assert isinstance(output, dict)
    output["photo_relative_path"] = "journey/../../escape.jpg"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "trip": {"name": "Journey", "slug": "journey"},
                "assets": [asset],
            }
        )
    )
    with pytest.raises(ManifestError, match="unsafe path"):
        load_manifest(root, manifest)
    engine.dispose()


def test_unverified_file_is_not_available(tmp_path: Path) -> None:
    asset = _asset("3" * 64)
    output = asset["output"]
    assert isinstance(output, dict)
    output["verification_status"] = "PLANNED"
    root, manifest, engine = _setup(tmp_path, [asset])
    with session_factory(engine)() as session:
        report = import_manifest(session, root, manifest)
        assert (report.status, report.available_files, report.unavailable_files) == (
            "PARTIAL_AVAILABILITY",
            0,
            1,
        )
        assert session.scalar(select(AssetFile.availability_status)) == "UNVERIFIED"
    engine.dispose()


def test_missing_srt_does_not_remove_video(tmp_path: Path) -> None:
    asset = _asset("4" * 64, "YOUTUBE_16X9")
    output = asset["output"]
    source = asset["source"]
    assert isinstance(output, dict) and isinstance(source, dict)
    output["srt_relative_path"] = "journey/poi/YOUTUBE_16x9/video.srt"
    output["srt_sha256"] = "b" * 64
    source["srt_status"] = "paired"
    root, manifest, engine = _setup(tmp_path, [asset])
    (root / str(output["srt_relative_path"])).unlink()
    with session_factory(engine)() as session:
        report = import_manifest(session, root, manifest)
        assert (report.available_files, report.missing_files) == (1, 1)
        files = {
            row.role: row.availability_status
            for row in session.scalars(select(AssetFile))
        }
        assert files == {"ORIGINAL": "AVAILABLE", "SRT": "MISSING"}
    engine.dispose()


@pytest.mark.parametrize(
    "bad_path",
    [
        "C:/source/photo.jpg",
        "journey/../escape.jpg",
        "journey\\photo.jpg",
        "/tmp/photo.jpg",
    ],
)
def test_rejects_unsafe_output_paths(tmp_path: Path, bad_path: str) -> None:
    asset = _asset("5" * 64)
    output = asset["output"]
    assert isinstance(output, dict)
    output["photo_relative_path"] = bad_path
    root, manifest, engine = _setup(tmp_path, [])
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "trip": {"name": "Journey", "slug": "journey"},
                "assets": [asset],
            }
        )
    )
    with pytest.raises(ManifestError):
        load_manifest(root, manifest)
    engine.dispose()


def test_catalog_migration_round_trip(tmp_path: Path) -> None:
    from sqlalchemy import inspect

    _, _, engine = _setup(tmp_path, [])
    tables = {"catalog_assets", "asset_files", "manifest_imports"}
    schema = inspect(engine)
    assert tables <= set(schema.get_table_names())
    assert any(
        item["column_names"] == ["asset_id"]
        for item in schema.get_unique_constraints("catalog_assets")
    )
    assert any(
        item["column_names"] == ["catalog_asset_id", "role"]
        for item in schema.get_unique_constraints("asset_files")
    )
    assert any(
        item["referred_table"] == "trips"
        for item in schema.get_foreign_keys("catalog_assets")
    )
    assert any(
        item["referred_table"] == "catalog_assets"
        for item in schema.get_foreign_keys("asset_files")
    )
    engine.dispose()
    settings = ServerSettings(
        database_path=tmp_path / "test.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.downgrade(alembic_config(settings), "0002_ingest")
    engine = create_engine_from_settings(settings)
    assert not tables & set(inspect(engine).get_table_names())
    engine.dispose()


def test_reimport_updates_verification_state_without_duplication(
    tmp_path: Path,
) -> None:
    asset = _asset("6" * 64)
    root, manifest, engine = _setup(tmp_path, [asset])
    with session_factory(engine)() as session:
        import_manifest(session, root, manifest)
        output = asset["output"]
        assert isinstance(output, dict)
        output["verification_status"] = "PLANNED"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "trip": {"name": "Journey", "slug": "journey"},
                    "assets": [asset],
                }
            )
        )
        report = import_manifest(session, root, manifest)
        assert (report.created_assets, report.created_files) == (0, 0)
        assert session.scalar(select(CatalogAsset.verification_status)) == "PLANNED"
        assert session.scalar(select(AssetFile.availability_status)) == "UNVERIFIED"
    engine.dispose()


def test_hash_verification_reports_mismatch(tmp_path: Path) -> None:
    asset = _asset("7" * 64)
    root, manifest, engine = _setup(tmp_path, [asset])
    with session_factory(engine)() as session:
        report = import_manifest(session, root, manifest, verify_hash=True)
        assert report.status == "PARTIAL_AVAILABILITY"
        assert session.scalar(select(AssetFile.availability_status)) == "HASH_MISMATCH"
    engine.dispose()


def test_video_without_srt_and_nullable_photo_metadata(tmp_path: Path) -> None:
    video = _asset("8" * 64, "INSTAGRAM_9X16")
    photo = _asset("9" * 64)
    root, manifest, engine = _setup(tmp_path, [video, photo])
    with session_factory(engine)() as session:
        report = import_manifest(session, root, manifest)
        assert (report.created_assets, report.created_files) == (2, 2)
        rows = {row.asset_id: row for row in session.scalars(select(CatalogAsset))}
        assert rows["8" * 64].classification == "INSTAGRAM_9X16"
        assert rows["8" * 64].media_type == "VIDEO"
        assert rows["9" * 64].media_type == "PHOTO"
        assert rows["9" * 64].codec is None
        assert rows["9" * 64].duration_ms is None
        assert rows["9" * 64].capture_date is None
        assert {row.role for row in session.scalars(select(AssetFile))} == {"ORIGINAL"}
    engine.dispose()


def test_invalid_classification_rejects_entire_manifest(tmp_path: Path) -> None:
    asset = _asset("a" * 64)
    asset["classification"] = "UNKNOWN"
    root, manifest, engine = _setup(tmp_path, [asset])
    with pytest.raises(ManifestError, match="classification"):
        load_manifest(root, manifest)
    with session_factory(engine)() as session:
        assert session.scalar(select(func.count()).select_from(Trip)) == 0
    engine.dispose()


def test_reuses_compatible_legacy_trip_without_changing_its_path(
    tmp_path: Path,
) -> None:
    asset = _asset("b" * 64)
    root, manifest, engine = _setup(tmp_path, [asset])
    with session_factory(engine)() as session:
        session.add(
            Trip(
                name="Journey",
                slug="journey",
                nas_rel_path="trips/journey/00_INBOX_ORIGINALS",
            )
        )
        session.commit()
        report = import_manifest(session, root, manifest)
        assert report.status == "IMPORTED"
        assert session.scalar(select(func.count()).select_from(Trip)) == 1
        assert (
            session.scalar(select(Trip.nas_rel_path))
            == "trips/journey/00_INBOX_ORIGINALS"
        )
        assert session.scalar(select(func.count()).select_from(CatalogAsset)) == 1
    engine.dispose()


def test_known_hash_mismatch_requires_new_hash_check_to_clear(tmp_path: Path) -> None:
    asset = _asset("c" * 64)
    root, manifest, engine = _setup(tmp_path, [asset])
    with session_factory(engine)() as session:
        assert (
            import_manifest(session, root, manifest, verify_hash=True).status
            == "PARTIAL_AVAILABILITY"
        )
        report = import_manifest(session, root, manifest)
        assert report.status == "PARTIAL_AVAILABILITY"
        assert session.scalar(select(AssetFile.availability_status)) == "HASH_MISMATCH"
    engine.dispose()
