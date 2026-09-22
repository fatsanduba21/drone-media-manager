"""Operator command for Phase 2A manifest preview and import."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path

from drone_media_manager.catalog.importer import (
    ManifestError,
    import_manifest,
    preview_manifest,
)
from drone_media_manager.cli.server import alembic_config, verify_database_revision
from drone_media_manager.config import ServerSettings, get_server_settings
from drone_media_manager.db.session import create_engine_from_settings, session_factory


def main(
    argv: Sequence[str] | None = None,
    *,
    settings_loader: Callable[[], ServerSettings] = get_server_settings,
) -> int:
    parser = argparse.ArgumentParser(prog="dmm-catalog")
    parser.add_argument("command", choices=("preview", "import"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--verify-hash", action="store_true", help="hash every physical media file"
    )
    args = parser.parse_args(argv)
    settings = settings_loader()
    engine = create_engine_from_settings(settings)
    try:
        verify_database_revision(engine, alembic_config(settings))
        with session_factory(engine)() as session:
            try:
                operation = (
                    preview_manifest if args.command == "preview" else import_manifest
                )
                report = operation(
                    session,
                    settings.omv_root,
                    args.manifest,
                    verify_hash=args.verify_hash,
                )
            except (ManifestError, OSError) as error:
                print(
                    json.dumps(
                        {
                            "status": "UNSUPPORTED_SCHEMA"
                            if str(error).startswith("UNSUPPORTED_SCHEMA:")
                            else "ERROR",
                            "error": str(error),
                        },
                        ensure_ascii=False,
                    )
                )
                return 2
            print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
            return 2 if report.status in {"CONFLICT", "PARTIAL_AVAILABILITY"} else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
