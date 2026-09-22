from __future__ import annotations

import hashlib
import json
from pathlib import Path

from drone_media_manager.ingest.inventory import build_inventory
from drone_media_manager.sources.discovery import (
    FilesystemReadOnlySource,
    source_from_explicit_path,
)
from drone_media_manager.worker.handlers.ingest import IngestJobHandler
from drone_media_manager.worker.snapshots import LocalSnapshotRegistry


def test_handler_resolves_source_and_destination_from_logical_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "DCIM").mkdir()
    (source / "DCIM" / "clip.mp4").write_bytes(b"media")
    descriptor = source_from_explicit_path(source)
    inventory = build_inventory(FilesystemReadOnlySource(descriptor))
    registry = LocalSnapshotRegistry()
    registry.register("snapshot-1", descriptor, inventory)
    omv = tmp_path / "omv"

    result = IngestJobHandler(snapshot_registry=registry, omv_root=omv).execute(
        {
            "payload": {
                "ingest_id": "ingest-1",
                "source_kind": "LOCAL",
                "source_fingerprint": "f" * 64,
                "snapshot_id": "snapshot-1",
                "items": [
                    {
                        "id": "item-1",
                        "source_rel_path": "DCIM/clip.mp4",
                        "source_size_bytes": 5,
                        "destination_rel_path": "trips/trip/00_INBOX_ORIGINALS/DCIM/clip.mp4",
                        "partial_rel_path": "trips/trip/00_INBOX_ORIGINALS/DCIM/.clip.mp4.item-1.partial",
                    }
                ],
            }
        }
    )

    assert result.status == "VERIFIED"
    assert (
        omv / "trips/trip/00_INBOX_ORIGINALS/DCIM/clip.mp4"
    ).read_bytes() == b"media"
    assert hashlib.sha256(
        (omv / "trips/trip/00_INBOX_ORIGINALS/DCIM/clip.mp4").read_bytes()
    ).hexdigest()
    manifest = omv / "trips/trip/05_MANIFESTS/ingest_manifest.ingest-1.json"
    assert manifest.exists()
    assert str(source) not in manifest.read_text(encoding="utf-8")


def test_mixed_fixture_copy_verify_manifest_and_reimport_are_idempotent(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "sources" / "mixed"
    omv = tmp_path / "omv"
    descriptor = source_from_explicit_path(fixture)
    inventory = build_inventory(FilesystemReadOnlySource(descriptor))
    registry = LocalSnapshotRegistry()
    registry.register("mixed-snapshot", descriptor, inventory)
    payload = {
        "ingest_id": "mixed-ingest",
        "snapshot_id": "mixed-snapshot",
        "source_kind": "LOCAL",
        "source_fingerprint": "a" * 64,
        "items": [
            {
                "id": f"item-{index}",
                "source_rel_path": entry.relative_path.as_posix(),
                "source_size_bytes": entry.stat.size,
                "destination_rel_path": f"trips/mixed/00_INBOX_ORIGINALS/{entry.relative_path.as_posix()}",
                "partial_rel_path": f"trips/mixed/00_INBOX_ORIGINALS/{entry.relative_path.parent.as_posix()}/.{entry.relative_path.name}.item-{index}.partial",
                "pair_status": next(
                    item.pair_status.value
                    for item in inventory.items
                    if entry in item.entries
                ),
            }
            for index, entry in enumerate(inventory.entries)
        ],
    }
    before = hashlib.sha256(
        b"".join(entry.absolute_path.read_bytes() for entry in inventory.entries)
    ).hexdigest()
    handler = IngestJobHandler(snapshot_registry=registry, omv_root=omv)

    assert handler.execute({"payload": payload}).status == "VERIFIED"
    assert handler.execute({"payload": payload}).status == "VERIFIED"

    manifest = omv / "trips/mixed/05_MANIFESTS/ingest_manifest.mixed-ingest.json"
    body = json.loads(manifest.read_text(encoding="utf-8"))
    assert {item["pair_status"] for item in body["items"]} >= {
        "PAIRED",
        "VIDEO_WITHOUT_SRT",
        "ORPHAN_SRT",
    }
    after = hashlib.sha256(
        b"".join(entry.absolute_path.read_bytes() for entry in inventory.entries)
    ).hexdigest()
    assert before == after
