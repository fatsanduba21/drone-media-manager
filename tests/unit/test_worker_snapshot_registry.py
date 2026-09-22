from __future__ import annotations

from pathlib import Path

import pytest

from drone_media_manager.ingest.inventory import build_inventory
from drone_media_manager.sources.discovery import (
    FilesystemReadOnlySource,
    source_from_explicit_path,
)
from drone_media_manager.worker.snapshots import LocalSnapshotRegistry


def test_snapshot_registry_resolves_logical_source_paths_without_persisting_absolute_paths(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "DCIM").mkdir()
    (source / "DCIM" / "clip.mp4").write_bytes(b"clip")
    descriptor = source_from_explicit_path(source)
    inventory = build_inventory(FilesystemReadOnlySource(descriptor))

    registry = LocalSnapshotRegistry()
    registry.register("snapshot-1", descriptor, inventory)

    entry = registry.resolve_entry("snapshot-1", "DCIM/clip.mp4")
    assert entry.relative_path.as_posix() == "DCIM/clip.mp4"
    assert entry.absolute_path == source / "DCIM" / "clip.mp4"
    assert "snapshot-1" in registry.snapshot_ids()
    assert registry.serialized("snapshot-1")["source_root"] is None


def test_snapshot_registry_rejects_unregistered_or_escaping_paths() -> None:
    registry = LocalSnapshotRegistry()

    with pytest.raises(KeyError):
        registry.resolve_entry("missing", "clip.mp4")


def test_snapshot_registry_reopens_from_local_worker_state(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "clip.mp4").write_bytes(b"clip")
    descriptor = source_from_explicit_path(source)
    inventory = build_inventory(FilesystemReadOnlySource(descriptor))
    state = tmp_path / "worker-state" / "snapshots.json"

    LocalSnapshotRegistry(state).register("snapshot-1", descriptor, inventory)
    reopened = LocalSnapshotRegistry(state)

    assert reopened.resolve_entry("snapshot-1", "clip.mp4").stat.size == 4
    assert str(source) not in reopened.serialized("snapshot-1").__repr__()
