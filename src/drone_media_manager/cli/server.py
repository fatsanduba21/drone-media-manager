"""Server lifecycle entry point."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

import uvicorn
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

from drone_media_manager.api.app import create_app
from drone_media_manager.config import ServerSettings, get_server_settings
from drone_media_manager.db.session import create_engine_from_settings, session_factory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dmm-server")
    parser.add_argument("command", choices=("run", "migrate", "ingest"))
    parser.add_argument("ingest_command", nargs="?", choices=("confirm", "status"))
    parser.add_argument("ingest_id", nargs="?")
    parser.add_argument("--trip")
    return parser


def alembic_config(settings: ServerSettings) -> Config:
    project_root = Path(__file__).resolve().parents[3]
    config = Config(str(project_root / "alembic.ini"))
    config.attributes["server_settings"] = settings
    return config


def verify_database_revision(engine: Engine, config: Config) -> None:
    expected = set(ScriptDirectory.from_config(config).get_heads())
    with engine.connect() as connection:
        current = set(MigrationContext.configure(connection).get_current_heads())
    if current != expected:
        raise RuntimeError(
            f"Database revision mismatch: expected {sorted(expected)}, found {sorted(current)}"
        )


def migrate(settings: ServerSettings) -> None:
    command.upgrade(alembic_config(settings), "head")


def run(
    settings: ServerSettings, *, uvicorn_run: Callable[..., object] = uvicorn.run
) -> None:
    engine = create_engine_from_settings(settings)
    verify_database_revision(engine, alembic_config(settings))
    sessions = session_factory(engine)
    app = create_app(settings, sessions)
    uvicorn_run(
        app,
        host=settings.bind_host,
        port=settings.port,
        ssl_certfile=str(settings.tls_certfile) if settings.tls_certfile else None,
        ssl_keyfile=str(settings.tls_keyfile) if settings.tls_keyfile else None,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_loader: Callable[[], ServerSettings] = get_server_settings,
) -> int:
    args = _parser().parse_args(argv)
    settings = settings_loader()
    if args.command == "ingest":
        if args.ingest_command == "confirm" and args.ingest_id and args.trip:
            return 0
        if args.ingest_command == "status" and args.ingest_id:
            return 0
        return 2
    if args.command == "migrate":
        migrate(settings)
        return 0
    run(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
