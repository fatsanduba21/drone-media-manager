from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect

from drone_media_manager.config import ServerSettings

INGEST_TABLES = {
    "trips",
    "source_snapshots",
    "source_snapshot_entries",
    "ingest_jobs",
    "ingest_items",
    "media_files",
    "media_pairs",
    "file_operations",
}


def _settings(database_path: Path) -> ServerSettings:
    return ServerSettings(
        database_path=database_path,
        omv_root=database_path.parent / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )


def _alembic_config(settings: ServerSettings) -> Config:
    project_root = Path(__file__).resolve().parents[2]
    config = Config(str(project_root / "alembic.ini"))
    config.attributes["server_settings"] = settings
    return config


def test_ingest_migration_round_trip_creates_and_removes_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "ingest.sqlite3"
    config = _alembic_config(_settings(database_path))

    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    assert INGEST_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()

    command.downgrade(config, "0001_core")

    engine = create_engine(f"sqlite:///{database_path}")
    assert not INGEST_TABLES & set(inspect(engine).get_table_names())
    engine.dispose()
