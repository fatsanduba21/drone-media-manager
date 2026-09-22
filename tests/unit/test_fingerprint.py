from __future__ import annotations

from pathlib import Path

from drone_media_manager.ingest.fingerprint import fingerprint_inventory
from drone_media_manager.ingest.inventory import build_inventory
from drone_media_manager.sources.discovery import (
    FilesystemReadOnlySource,
    source_from_explicit_path,
)


def test_fingerprint_is_independent_of_enumeration_order(tmp_path: Path) -> None:
    (tmp_path / "B.MP4").write_bytes(b"second")
    (tmp_path / "A.SRT").write_bytes(b"first")
    inventory = build_inventory(
        FilesystemReadOnlySource(source_from_explicit_path(tmp_path))
    )

    assert fingerprint_inventory(inventory) == fingerprint_inventory(
        inventory.reversed()
    )


def test_fingerprint_changes_when_inventory_metadata_changes(tmp_path: Path) -> None:
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"first")
    source = FilesystemReadOnlySource(source_from_explicit_path(tmp_path))
    original = build_inventory(source)

    media.write_bytes(b"second")
    changed = build_inventory(source)

    assert fingerprint_inventory(original) != fingerprint_inventory(changed)
