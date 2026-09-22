"""Operational preview/import CLI behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from pydantic import SecretStr

from drone_media_manager.cli.catalog import main
from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings


def test_preview_and_import_commands(tmp_path: Path) -> None:
    root = tmp_path / "omv"
    root.mkdir()
    trip = root / "journey"
    trip.mkdir()
    manifest = trip / "MANIFESTO.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "trip": {"name": "Journey", "slug": "journey"},
                "assets": [],
            }
        )
    )
    settings = ServerSettings(
        database_path=tmp_path / "catalog.sqlite3",
        omv_root=root,
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    assert main(["preview", str(manifest)], settings_loader=lambda: settings) == 0
    assert main(["import", str(manifest)], settings_loader=lambda: settings) == 0


def test_unsupported_schema_has_distinct_cli_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "omv"
    root.mkdir()
    trip = root / "journey"
    trip.mkdir()
    manifest = trip / "MANIFESTO.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "trip": {"name": "Journey", "slug": "journey"},
                "assets": [],
            }
        )
    )
    settings = ServerSettings(
        database_path=tmp_path / "catalog.sqlite3",
        omv_root=root,
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    assert main(["import", str(manifest)], settings_loader=lambda: settings) == 2
    assert '"status": "UNSUPPORTED_SCHEMA"' in capsys.readouterr().out
