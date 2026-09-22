from __future__ import annotations

from pathlib import Path

import pytest

from drone_media_manager.domain.enums import PairStatus
from drone_media_manager.ingest.inventory import build_inventory
from drone_media_manager.sources.discovery import (
    FilesystemReadOnlySource,
    source_from_explicit_path,
)


@pytest.fixture
def mixed_source() -> FilesystemReadOnlySource:
    fixture_root = Path(__file__).parents[1] / "fixtures" / "sources" / "mixed"
    return FilesystemReadOnlySource(source_from_explicit_path(fixture_root))


def test_inventory_preserves_optional_srt_states(
    mixed_source: FilesystemReadOnlySource,
) -> None:
    inventory = build_inventory(mixed_source)

    assert [(item.stem, item.pair_status.value) for item in inventory.items] == [
        ("DJI_0001", "PAIRED"),
        ("DJI_0002", "VIDEO_WITHOUT_SRT"),
        ("ORPHAN", "ORPHAN_SRT"),
    ]
    assert inventory.items[0].pair_status is PairStatus.PAIRED
    assert inventory.total_bytes == sum(entry.stat.size for entry in inventory.entries)


def test_inventory_pairs_same_stems_only_within_the_same_directory(
    tmp_path: Path,
) -> None:
    (tmp_path / "A").mkdir()
    (tmp_path / "B").mkdir()
    (tmp_path / "A" / "same.mp4").write_bytes(b"video-a")
    (tmp_path / "B" / "same.srt").write_bytes(b"srt-b")
    source = FilesystemReadOnlySource(source_from_explicit_path(tmp_path))

    inventory = build_inventory(source)

    assert [item.pair_status for item in inventory.items] == [
        PairStatus.VIDEO_WITHOUT_SRT,
        PairStatus.ORPHAN_SRT,
    ]
