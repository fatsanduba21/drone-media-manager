from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from drone_media_manager.domain.enums import SourceKind
from drone_media_manager.ingest.inventory import build_inventory
from drone_media_manager.ingest.preflight import PreflightPolicy, run_preflight
from drone_media_manager.sources.models import (
    CanonicalSourceRoot,
    SourceDescriptor,
    SourceEntry,
    SourceStat,
)
from drone_media_manager.storage.capacity import Capacity
from drone_media_manager.storage.destination import DestinationPlanner, TripDestination
from drone_media_manager.storage.roots import RootMapper


@dataclass
class Source:
    entry: SourceEntry

    def iter_files(self):
        yield self.entry

    def stat(self, entry: SourceEntry) -> SourceStat:
        return self.entry.stat


@dataclass
class FakeCapacity:
    available_bytes: int
    total_bytes: int

    def inspect(self, root: Path) -> Capacity:
        return Capacity(self.available_bytes, self.total_bytes)


def _inventory(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    file = source_root / "clip.mp4"
    file.write_bytes(b"video")
    entry = SourceEntry(
        CanonicalSourceRoot(source_root, "source"),
        Path("clip.mp4"),
        SourceStat(5, file.stat().st_mtime_ns, "file-1"),
    )
    descriptor = SourceDescriptor(
        SourceKind.LOCAL, entry.root, "source", "volume", False
    )
    source = Source(entry)
    source.descriptor = descriptor
    return build_inventory(source), source, entry


def test_preflight_blocks_when_space_is_below_required_margin(tmp_path: Path) -> None:
    inventory, source, entry = _inventory(tmp_path)
    omv = tmp_path / "omv"
    omv.mkdir()
    planned = DestinationPlanner(RootMapper(omv)).plan(
        TripDestination("id", "trip"), entry
    )

    report = run_preflight(
        inventory,
        source,
        planned,
        PreflightPolicy(reserve_bytes=1),
        FakeCapacity(5, 100),
    )

    assert report.allowed is False
    assert report.errors[0].code == "insufficient_space"


def test_preflight_detects_source_change_without_writing_source(tmp_path: Path) -> None:
    inventory, source, entry = _inventory(tmp_path)
    omv = tmp_path / "omv"
    omv.mkdir()
    planned = DestinationPlanner(RootMapper(omv)).plan(
        TripDestination("id", "trip"), entry
    )
    original = entry.absolute_path.read_bytes()
    source.entry = SourceEntry(
        entry.root, entry.relative_path, SourceStat(6, 2, "changed")
    )

    report = run_preflight(
        inventory, source, planned, PreflightPolicy(), FakeCapacity(100, 100)
    )

    assert report.errors[0].code == "source_changed"
    assert entry.absolute_path.read_bytes() == original
