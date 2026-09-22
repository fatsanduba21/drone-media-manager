from __future__ import annotations

from pathlib import Path

import pytest

from drone_media_manager.sources.models import (
    CanonicalSourceRoot,
    SourceEntry,
    SourceStat,
)
from drone_media_manager.storage.destination import DestinationPlanner, TripDestination
from drone_media_manager.storage.roots import RootMapper, UnsafePath


def _entry(tmp_path: Path) -> SourceEntry:
    root = tmp_path / "source"
    root.mkdir()
    file = root / "DCIM" / "clip.mp4"
    file.parent.mkdir()
    file.write_bytes(b"x")
    return SourceEntry(
        CanonicalSourceRoot(root, "source"),
        Path("DCIM/clip.mp4"),
        SourceStat(1, file.stat().st_mtime_ns, "file"),
    )


def test_destination_never_uses_source_absolute_path(tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    planned = DestinationPlanner(RootMapper(tmp_path / "omv")).plan(
        TripDestination("trip-id", "my-trip"), entry
    )

    assert planned.relative_path.value.startswith("trips/")
    assert str(entry.absolute_path) not in planned.relative_path.value


def test_destination_rejects_unsafe_trip_slug(tmp_path: Path) -> None:
    with pytest.raises(UnsafePath):
        DestinationPlanner(RootMapper(tmp_path / "omv")).plan(
            TripDestination("id", "../escape"), _entry(tmp_path)
        )
