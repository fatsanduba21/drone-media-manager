"""Existing Phase 2D and 3A databases converge without losing rows."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from pydantic import SecretStr

from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings


@pytest.mark.parametrize("starting_revision", ["0005_gallery_auth", "0005_grouping"])
def test_existing_branch_head_upgrades_without_losing_data(
    tmp_path: Path, starting_revision: str
) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "branch.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    config = alembic_config(settings)
    command.upgrade(config, starting_revision)
    with sqlite3.connect(settings.database_path) as database:
        if starting_revision == "0005_gallery_auth":
            database.execute(
                "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                ("user-1", "existing", "hash"),
            )
            database.execute(
                """INSERT INTO trips
                (id, name, slug, nas_rel_path, created_at, updated_at)
                VALUES ('trip-1', 'Existing', 'existing', 'existing',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
            )
            database.execute(
                """INSERT INTO catalog_assets
                (id, asset_id, trip_id, media_type, classification, verification_status,
                 created_at, updated_at)
                VALUES ('asset-1', ?, 'trip-1', 'PHOTO', 'FOTOS', 'VERIFIED',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
                ("a" * 64,),
            )
            database.execute(
                """INSERT INTO asset_selections (id, user_id, catalog_asset_id)
                VALUES ('selection-1', 'user-1', 'asset-1')"""
            )
        else:
            database.execute(
                """INSERT INTO trips
                (id, name, slug, nas_rel_path, created_at, updated_at)
                VALUES ('trip-1', 'Existing', 'existing', 'existing',
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
            )
            database.execute(
                """INSERT INTO location_groups
                (id, trip_id, name_final, name_source, name_locked, created_at, updated_at)
                VALUES ('group-1', 'trip-1', 'Praia', 'human', 1,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"""
            )

    command.upgrade(config, "head")
    with sqlite3.connect(settings.database_path) as database:
        tables = {
            row[0]
            for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"users", "user_sessions", "asset_selections"} <= tables
        assert {"location_groups", "grouping_suggestions", "telemetry_tracks"} <= tables
        assert database.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall() == [("0007_location_names",)]
        assert "provider_place_id" in {
            row[1] for row in database.execute("PRAGMA table_info(location_groups)")
        }
        if starting_revision == "0005_gallery_auth":
            assert database.execute("SELECT username FROM users").fetchall() == [
                ("existing",)
            ]
            assert database.execute(
                "SELECT id, user_id, catalog_asset_id FROM asset_selections"
            ).fetchall() == [("selection-1", "user-1", "asset-1")]
        else:
            assert database.execute(
                "SELECT name_final, provider_place_id FROM location_groups"
            ).fetchall() == [("Praia", None)]
