"""Online SQLite backup and CLI behavior."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from pydantic import SecretStr

from drone_media_manager.cli.server import main
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.backup import BackupError, backup_sqlite


def settings(tmp_path: Path) -> ServerSettings:
    return ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )


def test_online_backup_includes_committed_wal_data_without_uncommitted_rows(
    tmp_path: Path,
) -> None:
    config = settings(tmp_path)
    with sqlite3.connect(config.database_path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE media (name TEXT NOT NULL)")
        writer.execute("INSERT INTO media VALUES ('committed')")
        writer.commit()
        writer.execute("INSERT INTO media VALUES ('uncommitted')")
        report = backup_sqlite(config)
        assert report.path.is_file()
        assert report.path != config.database_path
        assert report.size_bytes == report.path.stat().st_size
        assert report.sha256 == hashlib.sha256(report.path.read_bytes()).hexdigest()
        with sqlite3.connect(report.path) as copy:
            assert copy.execute("SELECT name FROM media").fetchall() == [("committed",)]
            assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert writer.execute("SELECT COUNT(*) FROM media").fetchone() == (2,)


def test_backup_rejects_existing_output_without_changing_it(tmp_path: Path) -> None:
    config = settings(tmp_path)
    with sqlite3.connect(config.database_path) as database:
        database.execute("CREATE TABLE media (id INTEGER)")
    destination = tmp_path / "existing.sqlite3"
    destination.write_bytes(b"keep me")
    with pytest.raises(BackupError, match="already exists"):
        backup_sqlite(config, destination)
    assert destination.read_bytes() == b"keep me"
    assert list(tmp_path.glob(".dmm-backup-*.tmp")) == []


def test_backup_does_not_create_a_missing_source(tmp_path: Path) -> None:
    config = settings(tmp_path)
    with pytest.raises(BackupError, match="does not exist"):
        backup_sqlite(config)
    assert not config.database_path.exists()
    assert list(tmp_path.glob("*.backup-*.sqlite3")) == []


def test_backup_cli_prints_verified_path_and_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = settings(tmp_path)
    with sqlite3.connect(config.database_path) as database:
        database.execute("CREATE TABLE media (id INTEGER)")
    output = tmp_path / "manual-backup.sqlite3"
    result = main(
        ["backup", "--output", str(output)],
        settings_loader=lambda: config,
    )
    assert result == 0
    assert output.is_file()
    stdout = capsys.readouterr().out
    assert f"backup={output}" in stdout
    assert "sha256=" in stdout


def test_backup_cli_reports_existing_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = settings(tmp_path)
    with sqlite3.connect(config.database_path) as database:
        database.execute("CREATE TABLE media (id INTEGER)")
    output = tmp_path / "manual-backup.sqlite3"
    output.write_bytes(b"existing")
    assert (
        main(["backup", "--output", str(output)], settings_loader=lambda: config) == 4
    )
    assert "already exists" in capsys.readouterr().err
    assert output.read_bytes() == b"existing"


def test_backup_cli_uses_unique_default_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = settings(tmp_path)
    with sqlite3.connect(config.database_path) as database:
        database.execute("CREATE TABLE media (id INTEGER)")
    assert main(["backup"], settings_loader=lambda: config) == 0
    first = list(tmp_path.glob("db.sqlite3.backup-*.sqlite3"))
    assert len(first) == 1
    assert str(first[0]) in capsys.readouterr().out
    assert main(["backup"], settings_loader=lambda: config) == 0
    assert len(list(tmp_path.glob("db.sqlite3.backup-*.sqlite3"))) == 2


def test_backup_failure_removes_partial_file(tmp_path: Path) -> None:
    config = settings(tmp_path)
    config.database_path.write_bytes(b"not a SQLite database")
    output = tmp_path / "failed.sqlite3"
    with pytest.raises(BackupError, match="SQLite backup failed"):
        backup_sqlite(config, output)
    assert not output.exists()
    assert list(tmp_path.glob(".dmm-backup-*.tmp")) == []
