from __future__ import annotations

from pathlib import Path

from drone_media_manager.ingest.copy import CopyEngine, CopyItem
from drone_media_manager.sources.models import (
    CanonicalSourceRoot,
    SourceEntry,
    SourceStat,
)


class Source:
    def __init__(self, entry: SourceEntry) -> None:
        self.entry = entry

    def open_read(self, entry: SourceEntry):
        return entry.absolute_path.open("rb")

    def stat(self, entry: SourceEntry) -> SourceStat:
        result = entry.absolute_path.stat()
        return SourceStat(result.st_size, result.st_mtime_ns, entry.stat.file_identity)


def test_resume_copies_only_missing_suffix(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    source_file = root / "clip.mp4"
    source_file.write_bytes(b"a" * (2 * 1024 * 1024))
    stat = SourceStat(
        source_file.stat().st_size, source_file.stat().st_mtime_ns, "file"
    )
    entry = SourceEntry(CanonicalSourceRoot(root, "source"), Path("clip.mp4"), stat)
    partial = tmp_path / "dest" / ".clip.partial"
    partial.parent.mkdir()
    partial.write_bytes(b"a" * 1024 * 1024)

    result = CopyEngine(Source(entry)).copy_or_resume(
        CopyItem("item", entry, partial, 1024 * 1024)
    )

    assert result.status == "COPIED"
    assert partial.read_bytes() == source_file.read_bytes()
