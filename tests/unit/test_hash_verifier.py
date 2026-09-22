from __future__ import annotations

import hashlib
from pathlib import Path

from drone_media_manager.ingest.verify import verify_copy
from drone_media_manager.sources.models import (
    CanonicalSourceRoot,
    SourceEntry,
    SourceStat,
)


def test_destination_hash_mismatch_never_verifies(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    partial = tmp_path / ".clip.partial"
    source.write_bytes(b"original!")
    partial.write_bytes(b"corrupted")

    result = verify_copy(
        source,
        partial,
        expected_source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
    )

    assert result.verified is False
    assert result.error_code == "destination_hash_mismatch"


def test_source_metadata_change_never_verifies(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp4"
    partial = tmp_path / ".clip.partial"
    source.write_bytes(b"original!")
    partial.write_bytes(b"original!")
    original_mtime = source.stat().st_mtime_ns
    source.write_bytes(b"changed!!")

    entry = SourceEntry(
        CanonicalSourceRoot(tmp_path, "source"),
        Path("clip.mp4"),
        SourceStat(9, original_mtime, "inventory-file"),
    )
    result = verify_copy(
        entry, partial, expected_source_hash=hashlib.sha256(b"original!").hexdigest()
    )

    assert result.verified is False
    assert result.error_code == "source_changed"
