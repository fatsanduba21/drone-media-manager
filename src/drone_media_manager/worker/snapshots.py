"""Worker-local source snapshot registrations.

The control plane stores only logical paths.  The selected source root is kept
in this process-local registry and is never part of the API payload, SQLite
records, or manifests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from drone_media_manager.domain.enums import SourceKind
from drone_media_manager.ingest.inventory import Inventory
from drone_media_manager.sources.models import (
    CanonicalSourceRoot,
    SourceDescriptor,
    SourceEntry,
    SourceStat,
)
from drone_media_manager.sources.paths import validate_source_entry
from drone_media_manager.storage.roots import LogicalMediaPath


@dataclass(frozen=True, slots=True)
class LocalSnapshot:
    snapshot_id: str
    descriptor: SourceDescriptor
    entries: dict[str, SourceEntry]


class LocalSnapshotRegistry:
    """Resolve server-provided logical source paths at the worker boundary."""

    def __init__(self, storage_path: Path | None = None) -> None:
        self._snapshots: dict[str, LocalSnapshot] = {}
        self._storage_path = storage_path
        if storage_path is not None and storage_path.exists():
            self._load()

    def register(
        self, snapshot_id: str, descriptor: SourceDescriptor, inventory: Inventory
    ) -> None:
        if inventory.source.root.path != descriptor.root.path:
            raise ValueError("inventory and snapshot descriptor roots differ")
        entries = {entry.relative_path.as_posix(): entry for entry in inventory.entries}
        self._snapshots[snapshot_id] = LocalSnapshot(snapshot_id, descriptor, entries)
        self._persist()

    def resolve_entry(self, snapshot_id: str, relative_path: str) -> SourceEntry:
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            raise KeyError(snapshot_id)
        logical = LogicalMediaPath.parse(relative_path)
        entry = snapshot.entries.get(logical.value)
        if entry is None:
            raise KeyError(relative_path)
        # Revalidate the boundary at use time in case the source was replaced.
        current = validate_source_entry(
            snapshot.descriptor.root,
            snapshot.descriptor.root.path.joinpath(*logical.parts),
        )
        # Keep the inventory stat as the expected pre-copy identity; the
        # verifier compares it with the current source before promotion.
        return SourceEntry(snapshot.descriptor.root, current.relative_path, entry.stat)

    def snapshot_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._snapshots))

    def descriptor(self, snapshot_id: str) -> SourceDescriptor:
        return self._snapshots[snapshot_id].descriptor

    def serialized(self, snapshot_id: str) -> dict[str, object]:
        snapshot = self._snapshots[snapshot_id]
        return {
            "snapshot_id": snapshot.snapshot_id,
            "source_kind": snapshot.descriptor.kind.value,
            "source_volume_identity": snapshot.descriptor.volume_identity,
            "source_root": None,
            "entries": tuple(sorted(snapshot.entries)),
        }

    def _persist(self) -> None:
        if self._storage_path is None:
            return
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            snapshot_id: {
                "source_root": str(snapshot.descriptor.root.path),
                "source_kind": snapshot.descriptor.kind.value,
                "source_volume_identity": snapshot.descriptor.volume_identity,
                "display_label": snapshot.descriptor.display_label,
                "entries": {
                    path: {
                        "size": entry.stat.size,
                        "mtime_ns": entry.stat.mtime_ns,
                        "file_identity": entry.stat.file_identity,
                    }
                    for path, entry in snapshot.entries.items()
                },
            }
            for snapshot_id, snapshot in self._snapshots.items()
        }
        temporary = self._storage_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temporary.replace(self._storage_path)

    def _load(self) -> None:
        assert self._storage_path is not None
        raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
        for snapshot_id, record in raw.items():
            root = Path(record["source_root"])
            descriptor = SourceDescriptor(
                kind=SourceKind(record["source_kind"]),
                root=CanonicalSourceRoot(root, str(root).casefold()),
                display_label=record["display_label"],
                volume_identity=record.get("source_volume_identity"),
                is_removable=SourceKind(record["source_kind"]) is SourceKind.REMOVABLE,
            )
            entries = {
                path: SourceEntry(
                    descriptor.root,
                    Path(path),
                    SourceStat(
                        int(meta["size"]),
                        int(meta["mtime_ns"]),
                        str(meta["file_identity"]),
                    ),
                )
                for path, meta in record["entries"].items()
            }
            self._snapshots[snapshot_id] = LocalSnapshot(
                snapshot_id, descriptor, entries
            )


_DEFAULT_REGISTRY = LocalSnapshotRegistry()


def default_snapshot_registry(
    storage_path: Path | None = None,
) -> LocalSnapshotRegistry:
    global _DEFAULT_REGISTRY
    if storage_path is not None and _DEFAULT_REGISTRY._storage_path != storage_path:
        _DEFAULT_REGISTRY = LocalSnapshotRegistry(storage_path)
    return _DEFAULT_REGISTRY
