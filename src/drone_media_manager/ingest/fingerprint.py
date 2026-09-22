"""Stable source-inventory identity distinct from content verification."""

from __future__ import annotations

import hashlib
import json

from drone_media_manager.ingest.inventory import Inventory


def fingerprint_inventory(inventory: Inventory) -> str:
    """Hash canonical source metadata independently of enumeration order."""

    entries = sorted(
        inventory.entries,
        key=lambda entry: entry.relative_path.as_posix(),
    )
    payload = {
        "source_kind": inventory.source.kind.value,
        "volume_identity": inventory.source.volume_identity,
        "entries": [
            {
                "relative_path": entry.relative_path.as_posix(),
                "size": entry.stat.size,
                "mtime_ns": entry.stat.mtime_ns,
            }
            for entry in entries
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
