"""Integration tests for the local SQLite schema migration contract."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from drone_media_manager.config import ServerSettings

APPLICATION_TABLES = {"workers", "jobs", "audit_events"}
CORE_INDEXES = {
    "ix_workers_status_last_seen_at",
    "ix_jobs_status_available_at",
    "ix_jobs_lease_expires_at",
    "ix_audit_events_entity_type_entity_id_occurred_at",
    "ix_audit_events_occurred_at",
}


def server_settings(database_path: Path) -> ServerSettings:
    """Build validated, local settings for a temporary migration database."""
    return ServerSettings(
        database_path=database_path,
        omv_root=database_path.parent / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )


def alembic_config(settings: ServerSettings | None = None) -> Config:
    """Return Alembic configuration carrying explicitly validated settings."""
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    if settings is not None:
        config.attributes["server_settings"] = settings
    return config


def test_core_migration_round_trip(tmp_path: Path) -> None:
    """Removing core tables on downgrade prevents stale schema from being reused."""
    database_path = tmp_path / "core.sqlite3"
    database_url = f"sqlite:///{database_path}"
    settings = server_settings(database_path)
    command.upgrade(alembic_config(settings), "head")

    upgrade_engine = create_engine(database_url)
    assert APPLICATION_TABLES <= set(inspect(upgrade_engine).get_table_names())
    assert "alembic_version" in inspect(upgrade_engine).get_table_names()
    assert CORE_INDEXES <= {index["name"] for table in APPLICATION_TABLES for index in inspect(upgrade_engine).get_indexes(table)}
    upgrade_engine.dispose()

    command.downgrade(alembic_config(settings), "base")

    downgrade_engine = create_engine(database_url)
    remaining_tables = set(inspect(downgrade_engine).get_table_names())
    assert not APPLICATION_TABLES & remaining_tables
    if "alembic_version" in remaining_tables:
        with downgrade_engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM alembic_version")) == 0
    downgrade_engine.dispose()


def test_migrations_require_validated_server_settings() -> None:
    """A migration command cannot bypass the local SQLite path policy."""
    with pytest.raises(CommandError, match="validated ServerSettings"):
        command.upgrade(alembic_config(), "head")


def test_audit_events_reject_update_and_delete(tmp_path: Path) -> None:
    """Audit records remain append-only even when SQL is issued directly."""
    database_path = tmp_path / "core.sqlite3"
    database_url = f"sqlite:///{database_path}"
    settings = server_settings(database_path)
    command.upgrade(alembic_config(settings), "head")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO audit_events (
                    id, actor, action, entity_type, entity_id, result,
                    details_json, correlation_id, occurred_at
                ) VALUES (
                    'audit-1', 'operator', 'create', 'job', 'job-1', 'success',
                    '{}', 'correlation-1', '2026-01-01T00:00:00+00:00'
                )
                """
            )
        )
    with engine.connect() as connection:
        with pytest.raises(IntegrityError, match="audit_events are immutable"):
            connection.execute(text("UPDATE audit_events SET result = 'failure'"))
        connection.rollback()
        with pytest.raises(IntegrityError, match="audit_events are immutable"):
            connection.execute(text("DELETE FROM audit_events"))
    engine.dispose()


def test_sqlite_engine_enforces_foreign_keys_and_busy_timeout(tmp_path: Path) -> None:
    """A missing worker lease is rejected and SQLite waits five seconds when busy."""
    from drone_media_manager.db.session import (
        create_engine_from_settings,
        session_factory,
    )

    database_path = tmp_path / "core.sqlite3"
    settings = server_settings(database_path)
    command.upgrade(alembic_config(settings), "head")

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
