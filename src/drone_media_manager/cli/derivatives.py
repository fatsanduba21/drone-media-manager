"""Local operator command for Phase 2B media generation."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict

from drone_media_manager.cli.server import alembic_config, verify_database_revision
from drone_media_manager.config import get_server_settings
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.derivatives.service import generate_derivatives


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dmm-derivatives")
    parser.add_argument("command", choices=("generate",))
    parser.add_argument("--trip", help="Process only one imported trip slug")
    args = parser.parse_args(argv)
    settings = get_server_settings()
    engine = create_engine_from_settings(settings)
    try:
        verify_database_revision(engine, alembic_config(settings))
        with session_factory(engine)() as session:
            report = generate_derivatives(session, settings, trip_slug=args.trip)
        print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
        return 2 if report.failed else 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
