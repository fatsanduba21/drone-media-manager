"""Deterministic media inventory and MP4/SRT pairing."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from drone_media_manager.domain.enums import PairStatus
from drone_media_manager.sources.models import SourceDescriptor, SourceEntry


class InventorySource(Protocol):
    """A read-only source that retains its non-secret descriptor."""

    descriptor: SourceDescriptor

    def iter_files(self) -> Iterator[SourceEntry]: ...


@dataclass(frozen=True, slots=True)
class InventoryItem:
    """One logical video/SRT pair or orphaned source entry."""

    stem: str
    pair_status: PairStatus
    video_entry: SourceEntry | None
    srt_entry: SourceEntry | None

    @property
    def entries(self) -> tuple[SourceEntry, ...]:
        return tuple(
            entry for entry in (self.video_entry, self.srt_entry) if entry is not None
        )


@dataclass(frozen=True, slots=True)
class Inventory:
    """A stable, source-relative snapshot used to request ingest confirmation."""

    source: SourceDescriptor
    items: tuple[InventoryItem, ...]
    entries: tuple[SourceEntry, ...]

    @property
    def total_bytes(self) -> int:
        return sum(entry.stat.size for entry in self.entries)

    def reversed(self) -> Inventory:
        """Return a deliberately reordered view for deterministic-hash tests."""

        return Inventory(
            source=self.source,
            items=tuple(reversed(self.items)),
            entries=tuple(reversed(self.entries)),
        )


def build_inventory(source: InventorySource, recursive: bool = True) -> Inventory:
    """Build a deterministic inventory without mutating or reopening the source."""

    candidates = list(source.iter_files())
    if not recursive:
        candidates = [
            entry for entry in candidates if len(entry.relative_path.parts) == 1
        ]
    media_entries = [
        entry
        for entry in candidates
        if entry.relative_path.suffix.casefold() in {".mp4", ".srt"}
    ]
    entries = tuple(sorted(media_entries, key=_entry_sort_key))
    grouped: dict[tuple[str, str], dict[str, SourceEntry]] = {}
    for entry in entries:
        key = (
            _normalized_path(entry.relative_path.parent),
            unicodedata.normalize("NFC", entry.relative_path.stem).casefold(),
        )
        grouped.setdefault(key, {})[entry.relative_path.suffix.casefold()] = entry

    items = tuple(
        _inventory_item(group)
        for _, group in sorted(grouped.items(), key=_group_sort_key)
    )
    return Inventory(source=source.descriptor, items=items, entries=entries)


def _inventory_item(group: dict[str, SourceEntry]) -> InventoryItem:
    video_entry = group.get(".mp4")
    srt_entry = group.get(".srt")
    primary = video_entry or srt_entry
    if primary is None:
        raise ValueError("inventory group must contain media")

    if video_entry is not None and srt_entry is not None:
        pair_status = PairStatus.PAIRED
    elif video_entry is not None:
        pair_status = PairStatus.VIDEO_WITHOUT_SRT
    else:
        pair_status = PairStatus.ORPHAN_SRT
    return InventoryItem(
        stem=primary.relative_path.stem,
        pair_status=pair_status,
        video_entry=video_entry,
        srt_entry=srt_entry,
    )


def _entry_sort_key(entry: SourceEntry) -> str:
    return _normalized_path(entry.relative_path)


def _group_sort_key(group: tuple[tuple[str, str], dict[str, SourceEntry]]) -> str:
    entries = group[1].values()
    return min(_entry_sort_key(entry) for entry in entries)


def _normalized_path(path: Path) -> str:
    return unicodedata.normalize("NFC", path.as_posix())
