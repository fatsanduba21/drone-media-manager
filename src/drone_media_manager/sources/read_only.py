"""The deliberately narrow capability granted to selected sources."""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO, Protocol, runtime_checkable

from drone_media_manager.sources.models import SourceEntry, SourceStat


@runtime_checkable
class ReadOnlySource(Protocol):
    """Expose only read operations for a confirmed source root."""

    def iter_files(self) -> Iterator[SourceEntry]: ...

    def open_read(self, entry: SourceEntry) -> BinaryIO: ...

    def stat(self, entry: SourceEntry) -> SourceStat: ...
