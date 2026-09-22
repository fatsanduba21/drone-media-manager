"""Create descriptors and read-only filesystem capabilities for selected sources."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

from drone_media_manager.domain.enums import SourceKind
from drone_media_manager.sources.models import (
    SourceDescriptor,
    SourceEntry,
    SourceStat,
)
from drone_media_manager.sources.paths import (
    canonicalize_source_root,
    validate_source_entry,
)

_DRIVE_REMOVABLE = 2


class FilesystemReadOnlySource:
    """Read files only after resolving every candidate beneath a source root."""

    def __init__(self, descriptor: SourceDescriptor) -> None:
        self.descriptor = descriptor

    def iter_files(self) -> Iterator[SourceEntry]:
        root = self.descriptor.root.path
        candidates = sorted(root.rglob("*"), key=lambda path: path.as_posix())
        for candidate in candidates:
            if candidate.is_file():
                yield validate_source_entry(self.descriptor.root, candidate)

    def open_read(self, entry: SourceEntry) -> BinaryIO:
        return self._validated_entry(entry).absolute_path.open("rb")

    def stat(self, entry: SourceEntry) -> SourceStat:
        return self._validated_entry(entry).stat

    def _validated_entry(self, entry: SourceEntry) -> SourceEntry:
        if entry.root != self.descriptor.root:
            raise ValueError("source entry belongs to a different source root")
        return validate_source_entry(self.descriptor.root, entry.absolute_path)


def discover_removable_sources() -> list[SourceDescriptor]:
    """Return discovered removable volumes, each with the same read-only contract."""

    return [
        _descriptor_for_root(root, kind=SourceKind.REMOVABLE, is_removable=True)
        for root in _iter_removable_roots()
    ]


def source_from_explicit_path(path: str | Path) -> SourceDescriptor:
    """Describe an explicitly selected local, mapped, or UNC source path."""

    raw_path = str(path)
    mapped_unc = _mapped_unc_identity(raw_path)
    kind = (
        SourceKind.NETWORK
        if raw_path.startswith(("\\\\", "//")) or mapped_unc
        else SourceKind.LOCAL
    )
    return _descriptor_for_root(
        Path(path),
        kind=kind,
        is_removable=False,
        volume_identity=mapped_unc,
    )


def _descriptor_for_root(
    path: Path,
    *,
    kind: SourceKind,
    is_removable: bool,
    volume_identity: str | None = None,
) -> SourceDescriptor:
    root = canonicalize_source_root(path)
    return SourceDescriptor(
        kind=kind,
        root=root,
        display_label=root.path.name or str(root.path),
        volume_identity=volume_identity or root.identity,
        is_removable=is_removable,
    )


def _iter_removable_roots() -> Iterator[Path]:
    """Yield Windows removable drive roots without touching their contents."""

    if os.name != "nt":
        return

    drive_mask = ctypes.windll.kernel32.GetLogicalDrives()
    for index in range(26):
        if drive_mask & (1 << index):
            root = Path(f"{chr(ord('A') + index)}:\\")
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(str(root))
            if drive_type == _DRIVE_REMOVABLE:
                yield root


def _mapped_unc_identity(path: str) -> str | None:
    """Preserve a mapped-drive's UNC identity when Windows can resolve it."""

    if os.name != "nt" or len(path) < 2 or path[1] != ":":
        return None

    buffer_size = ctypes.c_uint(32768)
    buffer = ctypes.create_unicode_buffer(buffer_size.value)
    result = ctypes.windll.mpr.WNetGetConnectionW(
        path[:2], buffer, ctypes.byref(buffer_size)
    )
    if result != 0:
        return None

    suffix = path[2:].lstrip("\\/")
    return os.path.normcase(str(Path(buffer.value) / suffix))
