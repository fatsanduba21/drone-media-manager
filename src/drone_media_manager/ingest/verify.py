"""Independent post-copy verification for safe ingest."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from drone_media_manager.sources.models import SourceEntry, SourceStat


@dataclass(frozen=True, slots=True)
class VerificationResult:
    verified: bool
    error_code: str | None = None
    source_sha256: str | None = None
    destination_sha256: str | None = None
    source_stat: SourceStat | None = None


def verify_copy(
    source: Path | SourceEntry,
    partial: Path,
    expected_source_hash: str,
) -> VerificationResult:
    """Hash source and destination independently and compare inventory metadata."""

    source_path, expected_stat = _source_details(source)
    try:
        before = _path_stat(source_path)
        if expected_stat is not None and before != expected_stat:
            return VerificationResult(False, "source_changed", source_stat=before)
        source_hash = _hash_file(source_path)
        after = _path_stat(source_path)
        if after != before or (expected_stat is not None and after != expected_stat):
            return VerificationResult(
                False, "source_changed", source_sha256=source_hash, source_stat=after
            )
        if source_hash != expected_source_hash:
            return VerificationResult(
                False,
                "source_hash_mismatch",
                source_sha256=source_hash,
                source_stat=after,
            )
    except OSError:
        return VerificationResult(False, "source_unavailable")

    try:
        destination_stat = partial.stat()
        if destination_stat.st_size != after.size:
            return VerificationResult(
                False,
                "destination_size_mismatch",
                source_sha256=source_hash,
                source_stat=after,
            )
        destination_hash = _hash_file(partial)
    except OSError:
        return VerificationResult(
            False,
            "destination_unavailable",
            source_sha256=source_hash,
            source_stat=after,
        )
    if destination_hash != source_hash:
        return VerificationResult(
            False,
            "destination_hash_mismatch",
            source_sha256=source_hash,
            destination_sha256=destination_hash,
            source_stat=after,
        )
    return VerificationResult(
        True,
        source_sha256=source_hash,
        destination_sha256=destination_hash,
        source_stat=after,
    )


def hash_file(path: Path) -> str:
    """Return a SHA-256 digest for a regular file."""

    return _hash_file(path)


def _source_details(source: Path | SourceEntry) -> tuple[Path, SourceStat | None]:
    if isinstance(source, SourceEntry):
        return source.absolute_path, source.stat
    return source, None


def _path_stat(path: Path) -> SourceStat:
    result = path.stat()
    return SourceStat(
        result.st_size, result.st_mtime_ns, f"{result.st_dev}:{result.st_ino}"
    )


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
