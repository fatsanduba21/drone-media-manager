"""Immutable, source-relative records for the ingest safety boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from drone_media_manager.domain.enums import SourceKind


@dataclass(frozen=True, slots=True)
class CanonicalSourceRoot:
    """A selected source root after canonicalization and safety validation."""

    path: Path
    identity: str


@dataclass(frozen=True, slots=True)
class SourceStat:
    """Stable source metadata used to detect changes during ingest."""

    size: int
    mtime_ns: int
    file_identity: str


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    """The non-secret identity and display information for a selected source."""

    kind: SourceKind
    root: CanonicalSourceRoot
    display_label: str
    volume_identity: str | None
    is_removable: bool

    def __post_init__(self) -> None:
        if self.is_removable != (self.kind is SourceKind.REMOVABLE):
            raise ValueError("source kind and removable flag disagree")


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """A source file addressed by a relative path below its selected root."""

    root: CanonicalSourceRoot
    relative_path: Path
    stat: SourceStat

    @property
    def absolute_path(self) -> Path:
        """Resolve this entry only at the source boundary, never for persistence."""

        return self.root.path.joinpath(*self.relative_path.parts)
