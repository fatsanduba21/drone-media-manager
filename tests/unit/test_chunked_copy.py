from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from drone_media_manager.ingest.copy import CopyEngine, CopyItem, PartialPrefixMismatch
from drone_media_manager.sources.models import (
    CanonicalSourceRoot,
    SourceEntry,
    SourceStat,
)


@dataclass
class Source:
    entry: SourceEntry

    def open_read(self, entry: SourceEntry):
        return entry.absolute_path.open("rb")

    def stat(self, entry: SourceEntry) -> SourceStat:
        result = entry.absolute_path.stat()
        return SourceStat(result.st_size, result.st_mtime_ns, entry.stat.file_identity)


def _item(tmp_path: Path) -> tuple[CopyEngine, CopyItem]:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_file = source_root / "clip.mp4"
    source_file.write_bytes(b"a" * (2 * 1024 * 1024))
    stat = SourceStat(
        source_file.stat().st_size, source_file.stat().st_mtime_ns, "file"
    )
    entry = SourceEntry(
        CanonicalSourceRoot(source_root, "source"), Path("clip.mp4"), stat
    )
    return CopyEngine(Source(entry)), CopyItem(
        "item", entry, tmp_path / "dest" / ".clip.partial", 1024 * 1024
    )


def test_interruption_preserves_partial_and_checkpoint(tmp_path: Path) -> None:
    engine, item = _item(tmp_path)
    calls = 0

    def cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls > 2

    outcome = engine.copy_or_resume(item, cancelled=cancelled)

    assert outcome.status == "INTERRUPTED"
    assert item.partial_path.stat().st_size == 2 * item.chunk_size


def test_resume_rejects_divergent_partial(tmp_path: Path) -> None:
    engine, item = _item(tmp_path)
    item.partial_path.parent.mkdir()
    item.partial_path.write_bytes(b"different prefix")

    with pytest.raises(PartialPrefixMismatch):
        engine.copy_or_resume(item)

    assert item.partial_path.read_bytes() == b"different prefix"
