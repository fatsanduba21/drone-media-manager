"""Consistent, non-overwriting online backups of the local SQLite database."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from drone_media_manager.config import ServerSettings


class BackupError(RuntimeError):
    """The backup was not published as a verified file."""


@dataclass(frozen=True)
class BackupReport:
    path: Path
    size_bytes: int
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def backup_sqlite(settings: ServerSettings, output: Path | None = None) -> BackupReport:
    """Snapshot a live SQLite database, verify it, then publish without overwrite."""
    source = settings.database_path.expanduser().resolve(strict=False)
    if not source.is_file():
        raise BackupError(f"SQLite database does not exist: {source}")
    if output is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = source.with_name(
            f"{source.name}.backup-{stamp}-{uuid4().hex[:8]}.sqlite3"
        )
    else:
        destination = output.expanduser().resolve(strict=False)
    if destination == source:
        raise BackupError("backup destination must differ from the SQLite database")
    if not destination.parent.is_dir():
        raise BackupError(f"backup directory does not exist: {destination.parent}")
    if destination.exists() or destination.is_symlink():
        raise BackupError(f"backup destination already exists: {destination}")

    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".dmm-backup-", suffix=".tmp", dir=destination.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        with (
            closing(
                sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=30)
            ) as original,
            closing(sqlite3.connect(temporary, timeout=30)) as copy,
        ):
            original.backup(copy, pages=1000, sleep=0.1)
            if copy.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise BackupError("SQLite integrity_check failed on backup")
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        digest = _sha256(temporary)
        size = temporary.stat().st_size
        os.link(temporary, destination)
        return BackupReport(destination, size, digest)
    except (OSError, sqlite3.Error) as error:
        raise BackupError(f"SQLite backup failed: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
