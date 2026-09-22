from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from drone_media_manager.ingest.manifest import build_manifest, write_manifest_atomic


def _ingest() -> SimpleNamespace:
    return SimpleNamespace(
        id="ingest-1",
        source_kind="REMOVABLE",
        source_fingerprint="fingerprint",
        items=[
            SimpleNamespace(
                source_rel_path="DCIM/clip.MP4",
                destination_rel_path="trip/clip.MP4",
                source_size_bytes=3,
                source_sha256="a" * 64,
                destination_sha256="a" * 64,
                pair_status="VIDEO_WITHOUT_SRT",
                error=None,
                status="VERIFIED",
            ),
            SimpleNamespace(
                source_rel_path="DCIM/orphan.SRT",
                destination_rel_path="trip/orphan.SRT",
                source_size_bytes=2,
                source_sha256="b" * 64,
                destination_sha256="b" * 64,
                pair_status="ORPHAN_SRT",
                error=None,
                status="VERIFIED",
            ),
        ],
    )


def test_manifest_contains_missing_and_orphan_srt_states() -> None:
    manifest = build_manifest(_ingest())

    assert {item.pair_status for item in manifest.items} >= {
        "VIDEO_WITHOUT_SRT",
        "ORPHAN_SRT",
    }


def test_manifest_write_is_canonical_and_idempotent(tmp_path: Path) -> None:
    manifest = build_manifest(_ingest())
    destination = tmp_path / "05_MANIFESTS" / "ingest_manifest.ingest-1.json"

    first = write_manifest_atomic(manifest, destination)
    second = write_manifest_atomic(manifest, destination)

    assert first.status == "WRITTEN"
    assert second.status == "IDENTICAL_EXISTING"
    assert json.loads(destination.read_text(encoding="utf-8"))["schema_version"] == 1
    assert str(tmp_path) not in destination.read_text(encoding="utf-8")


def test_manifest_write_preserves_divergent_existing_content(tmp_path: Path) -> None:
    destination = tmp_path / "05_MANIFESTS" / "ingest_manifest.ingest-1.json"
    destination.parent.mkdir()
    destination.write_text('{"other":true}', encoding="utf-8")

    result = write_manifest_atomic(build_manifest(_ingest()), destination)

    assert result.status == "DIVERGENT_CONFLICT"
    assert destination.read_text(encoding="utf-8") == '{"other":true}'
