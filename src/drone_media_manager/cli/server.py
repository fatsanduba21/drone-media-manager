"""Server lifecycle and local-admin ingest entry point."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
from types import SimpleNamespace

import httpx
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
    parser.add_argument("--revision", type=int, default=2)
    return parser


class AdminIngestClient:
    """Localhost-only HTTP client for confirmation and status lookup."""

    def __init__(self, settings: ServerSettings) -> None:
        scheme = "https" if settings.tls_certfile else "http"
        self._base = f"{scheme}://{settings.bind_host}:{settings.port}"
        self._client = httpx.Client(timeout=30.0)

    def confirm_ingest(
        self, snapshot_id: str, trip_id: str, revision: int
    ) -> SimpleNamespace:
        response = self._client.post(
            f"{self._base}/api/ingests",
            json={
                "snapshot_id": snapshot_id,
                "trip_id": trip_id,
                "revision": revision,
            },
        )
        response.raise_for_status()
        return SimpleNamespace(**response.json())

    def get_ingest(self, ingest_id: str) -> SimpleNamespace:
        response = self._client.get(f"{self._base}/api/ingests/{ingest_id}")
        response.raise_for_status()
        return SimpleNamespace(**response.json())


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
    admin_client_factory: Callable[
        [ServerSettings], AdminIngestClient
    ] = AdminIngestClient,
) -> int:
    args = _parser().parse_args(argv)
    settings = settings_loader()
    if args.command == "ingest":
        client = admin_client_factory(settings)
        if args.ingest_command == "confirm" and args.ingest_id and args.trip:
            result = client.confirm_ingest(args.ingest_id, args.trip, args.revision)
            print(f"ingest={result.ingest_id} status={result.status}")
            return 0
        if args.ingest_command == "status" and args.ingest_id:
            result = client.get_ingest(args.ingest_id)
            print(f"ingest={result.ingest_id} status={result.status}")
            return {"VERIFIED": 0, "INTERRUPTED": 3, "FAILED": 4}.get(result.status, 3)
        return 2
    if args.command == "migrate":
        migrate(settings)
        return 0
    run(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
