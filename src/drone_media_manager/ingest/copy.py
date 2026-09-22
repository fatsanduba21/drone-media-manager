"""Bounded, durable, prefix-safe source copy and resume engine."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from drone_media_manager.sources.models import SourceEntry, SourceStat
from drone_media_manager.sources.read_only import ReadOnlySource

_MIN_CHUNK_SIZE = 1024 * 1024
_MAX_CHUNK_SIZE = 64 * 1024 * 1024


class PartialPrefixMismatch(ValueError):
    """An existing partial does not match the source prefix and is preserved."""


@dataclass(frozen=True, slots=True)
class CopyItem:
    id: str
    source_entry: SourceEntry
    partial_path: Path
    chunk_size: int = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CopyOutcome:
    status: str
    bytes_copied: int
    source_sha256: str | None
    partial_path: Path
    final_source_stat: SourceStat | None


class CopyEngine:
    def __init__(self, source: ReadOnlySource) -> None:
        self.source = source

    def copy_or_resume(
        self,
        item: CopyItem,
        progress: Callable[[int], None] = lambda _: None,
        cancelled: Callable[[], bool] = lambda: False,
        lease_valid: Callable[[], bool] = lambda: True,
    ) -> CopyOutcome:
        if not _MIN_CHUNK_SIZE <= item.chunk_size <= _MAX_CHUNK_SIZE:
            raise ValueError("chunk_size must be between 1 and 64 MiB")
        initial = self.source.stat(item.source_entry)
        partial = item.partial_path
        partial.parent.mkdir(parents=True, exist_ok=True)
        if partial.exists():
            self._assert_prefix(item, partial)
        copied = partial.stat().st_size if partial.exists() else 0
        hasher = hashlib.sha256()
        if copied:
            with partial.open("rb") as existing:
                for block in iter(lambda: existing.read(item.chunk_size), b""):
                    hasher.update(block)
        with (
            self.source.open_read(item.source_entry) as source,
            partial.open("ab") as target,
        ):
            source.seek(copied)
            while True:
                if cancelled() or not lease_valid():
                    return CopyOutcome("INTERRUPTED", copied, None, partial, None)
                block = source.read(item.chunk_size)
                if not block:
                    break
                target.write(block)
                target.flush()
                os.fsync(target.fileno())
                hasher.update(block)
                copied += len(block)
                progress(copied)
        final = self.source.stat(item.source_entry)
        if final != initial:
            return CopyOutcome("INTERRUPTED", copied, None, partial, final)
        return CopyOutcome("COPIED", copied, hasher.hexdigest(), partial, final)

    def _assert_prefix(self, item: CopyItem, partial: Path) -> None:
        length = partial.stat().st_size
        source_hash = hashlib.sha256()
        partial_hash = hashlib.sha256()
        with (
            self.source.open_read(item.source_entry) as source,
            partial.open("rb") as existing,
        ):
            remaining = length
            while remaining:
                block = source.read(min(item.chunk_size, remaining))
                if not block:
                    raise PartialPrefixMismatch("partial exceeds source length")
                source_hash.update(block)
                remaining -= len(block)
            for block in iter(lambda: existing.read(item.chunk_size), b""):
                partial_hash.update(block)
        if source_hash.digest() != partial_hash.digest():
            raise PartialPrefixMismatch("partial prefix differs from source")
