"""Canonicalize source roots and reject filesystem boundary escapes."""

from __future__ import annotations

import ntpath
import os
from pathlib import Path

from drone_media_manager.sources.models import (
    CanonicalSourceRoot,
    SourceEntry,
    SourceStat,
)

_WINDOWS_REPARSE_POINT = 0x0400


class UnsafeSourcePath(ValueError):
    """Raised when a candidate file is not safely beneath the selected root."""


def canonicalize_source_root(path: str | Path) -> CanonicalSourceRoot:
    """Return a canonical root identity while rejecting malformed values."""

    raw_path = str(path)
    if not raw_path or "\x00" in raw_path:
        raise UnsafeSourcePath("source roots must be non-empty and contain no NUL")

    resolved = Path(path).expanduser().resolve(strict=False)
    return CanonicalSourceRoot(path=resolved, identity=_source_identity(resolved))


def validate_source_entry(
    root: CanonicalSourceRoot, candidate: str | Path
) -> SourceEntry:
    """Validate one existing candidate and return only root-relative metadata."""

    raw_candidate = str(candidate)
    if "\x00" in raw_candidate:
        raise UnsafeSourcePath("source paths must contain no NUL")

    candidate_path = Path(candidate).expanduser()
    if _has_embedded_windows_absolute_path(raw_candidate, root.path):
        raise UnsafeSourcePath("source path must be relative to the confirmed root")

    resolved = candidate_path.resolve(strict=False)
    try:
        relative_path = resolved.relative_to(root.path)
    except ValueError as error:
        raise UnsafeSourcePath("source path escapes the confirmed root") from error

    if not relative_path.parts:
        raise UnsafeSourcePath("source entry must name a file below the root")
    _reject_escaping_reparse_point(root.path, candidate_path, resolved)

    try:
        stat_result = resolved.stat()
    except OSError as error:
        raise UnsafeSourcePath("source entry cannot be statted") from error
    if not resolved.is_file():
        raise UnsafeSourcePath("source entry must be a regular file")

    return SourceEntry(
        root=root,
        relative_path=relative_path,
        stat=SourceStat(
            size=stat_result.st_size,
            mtime_ns=stat_result.st_mtime_ns,
            file_identity=f"{stat_result.st_dev}:{stat_result.st_ino}",
        ),
    )


def _source_identity(path: Path) -> str:
    """Keep the canonical host identity transient and separate from manifests."""

    return os.path.normcase(str(path))


def _has_embedded_windows_absolute_path(raw: str, root: Path) -> bool:
    """Reject Windows drive and UNC input even when tests run on another OS."""

    if ntpath.isabs(raw) or ntpath.splitdrive(raw)[0]:
        try:
            Path(raw).resolve(strict=False).relative_to(root)
        except ValueError:
            return True
    return False


def _reject_escaping_reparse_point(root: Path, candidate: Path, resolved: Path) -> None:
    """Reject links and Windows reparse points whose target leaves the root."""

    try:
        lexical_relative = candidate.absolute().relative_to(root)
    except ValueError:
        lexical_relative = Path()

    current = root
    for part in lexical_relative.parts:
        current = current / part
        try:
            stat_result = current.lstat()
        except OSError:
            continue
        is_reparse_point = bool(
            getattr(stat_result, "st_file_attributes", 0) & _WINDOWS_REPARSE_POINT
        )
        if (current.is_symlink() or is_reparse_point) and not resolved.is_relative_to(
            root
        ):
            raise UnsafeSourcePath("source link escapes the confirmed root")
