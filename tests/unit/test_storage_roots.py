from __future__ import annotations

from pathlib import Path

import pytest

from drone_media_manager.storage.roots import (
    LogicalMediaPath,
    RootMapper,
    UnsafePath,
)


@pytest.mark.parametrize(
    "value",
    ["../outside.mp4", "/absolute.mp4", r"C:\outside.mp4", "a//b.mp4", "a/../b.mp4"],
)
def test_logical_path_rejects_root_escape_and_noncanonical_values(value: str) -> None:
    with pytest.raises(UnsafePath):
        LogicalMediaPath.parse(value)


def test_root_mapper_round_trips_relative_paths(tmp_path: Path) -> None:
    mapper = RootMapper(tmp_path)

    logical = LogicalMediaPath.parse("trips/2026/video.mp4")

    assert mapper.to_host_path(logical) == (tmp_path / "trips/2026/video.mp4").resolve()
    assert mapper.to_relative(tmp_path / "trips/2026/video.mp4") == logical


def test_root_mapper_rejects_physical_escape(tmp_path: Path) -> None:
    mapper = RootMapper(tmp_path)

    with pytest.raises(UnsafePath):
        mapper.to_host_path(LogicalMediaPath.parse("../outside.mp4"))

    with pytest.raises(UnsafePath):
        mapper.to_relative(tmp_path.parent / "outside.mp4")
