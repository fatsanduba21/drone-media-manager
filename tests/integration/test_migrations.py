"""Integration tests for the local SQLite schema migration contract."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from drone_media_manager.config import ServerSettings

APPLICATION_TABLES = {"workers", "jobs", "audit_events"}


def alembic_config(database_url: str) -> Config:
    """Return Alembic configuration pointed at an isolated SQLite database."""
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_core_migration_round_trip(tmp_path: Path) -> None:
    """Removing core tables on downgrade prevents stale schema from being reused."""
    database_url = f"sqlite:///{tmp_path / 'core.sqlite3'}"
    command.upgrade(alembic_config(database_url), "head")

    upgrade_engine = create_engine(database_url)
    assert APPLICATION_TABLES <= set(inspect(upgrade_engine).get_table_names())
    assert "alembic_version" in inspect(upgrade_engine).get_table_names()
    upgrade_engine.dispose()

    command.downgrade(alembic_config(database_url), "base")

    downgrade_engine = create_engine(database_url)
    remaining_tables = set(inspect(downgrade_engine).get_table_names())
    assert not APPLICATION_TABLES & remaining_tables
    if "alembic_version" in remaining_tables:
        with downgrade_engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM alembic_version")) == 0
    downgrade_engine.dispose()


def test_sqlite_engine_enforces_foreign_keys_and_busy_timeout(tmp_path: Path) -> None:
    """A missing worker lease is rejected and SQLite waits five seconds when busy."""
    from drone_media_manager.db.session import (
        create_engine_from_settings,
        session_factory,
    )

    database_path = tmp_path / "core.sqlite3"
    settings = ServerSettings(
        database_path=database_path,
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    database_url = f"sqlite:///{database_path}"
    command.upgrade(alembic_config(database_url), "head")

    engine = create_engine_from_settings(settings)
    factory = session_factory(engine)
    with factory() as session:
        assert session.bind is engine

    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys")) == 1
        assert connection.scalar(text("PRAGMA busy_timeout")) == 5000
        assert connection.scalar(text("PRAGMA journal_mode")) == "wal"
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO jobs (
                        id, kind, payload_json, status, revision, attempts, progress,
                        available_at, lease_worker_id, created_at, updated_at
                    ) VALUES (
                        'job-1', 'ingest', '{}', 'queued', 0, 0, 0,
                        '2026-01-01T00:00:00+00:00', 'missing-worker',
                        '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
                    )
                    """
                )
            )
    engine.dispose()
