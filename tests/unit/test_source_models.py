from __future__ import annotations

from pathlib import Path

import pytest

from drone_media_manager.domain.enums import SourceKind
from drone_media_manager.sources.models import (
    CanonicalSourceRoot,
    SourceDescriptor,
    SourceEntry,
    SourceStat,
)


def test_source_descriptor_is_immutable_and_marks_removable_sources(
    tmp_path: Path,
) -> None:
    root = CanonicalSourceRoot(path=tmp_path, identity=tmp_path.as_uri())
    descriptor = SourceDescriptor(
        kind=SourceKind.REMOVABLE,
        root=root,
        display_label="Drone card",
        volume_identity="volume-123",
        is_removable=True,
    )

    assert descriptor.root == root
    assert descriptor.is_removable is True
    with pytest.raises(AttributeError):
        descriptor.display_label = "changed"  # type: ignore[misc]


def test_source_entry_carries_only_relative_path_and_stat(tmp_path: Path) -> None:
    root = CanonicalSourceRoot(path=tmp_path, identity=tmp_path.as_uri())
    entry = SourceEntry(
        root=root,
        relative_path=Path("DCIM/DJI_0001.MP4"),
        stat=SourceStat(size=10, mtime_ns=123, file_identity="file-1"),
    )

    assert entry.relative_path.as_posix() == "DCIM/DJI_0001.MP4"
    assert entry.absolute_path == tmp_path / "DCIM/DJI_0001.MP4"
    assert entry.stat.size == 10
