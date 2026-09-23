"""Phase 2D user, session, and selection schema contract."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import CatalogAsset
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory


def _settings(tmp_path: Path) -> ServerSettings:
    return ServerSettings(
        database_path=tmp_path / "phase2d.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )


def test_0005_upgrade_and_downgrade(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    config = alembic_config(settings)
    command.upgrade(config, "head")
    engine = create_engine_from_settings(settings)
    tables = set(inspect(engine).get_table_names())
    assert {"users", "user_sessions", "asset_selections"} <= tables
    assert {"catalog_assets", "asset_files"} <= tables
    engine.dispose()

    command.downgrade(config, "0004_derivatives")
    engine = create_engine_from_settings(settings)
    tables = set(inspect(engine).get_table_names())
    assert not {"users", "user_sessions", "asset_selections"} & tables
    assert {"catalog_assets", "asset_files"} <= tables
    engine.dispose()


def test_selection_unique_pair_and_user_fk(tmp_path: Path) -> None:
    from drone_media_manager.db.models.auth import AssetSelection, User

    settings = _settings(tmp_path)
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    sessions = session_factory(engine)
    with sessions() as session:
        trip = Trip(name="Test", slug="test", nas_rel_path="test")
        session.add(trip)
        session.flush()
        asset = CatalogAsset(
            asset_id="a" * 64,
            trip_id=trip.id,
            media_type="PHOTO",
            classification="FOTOS",
            verification_status="VERIFIED",
        )
        user = User(username="editor", password_hash="hash")
        session.add_all([asset, user])
        session.flush()
        selection = AssetSelection(user_id=user.id, catalog_asset_id=asset.id)
        session.add(selection)
        session.commit()
        assert session.scalar(select(AssetSelection).where(AssetSelection.user_id == user.id)) is not None
        session.add(AssetSelection(user_id=user.id, catalog_asset_id=asset.id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(AssetSelection(user_id="missing", catalog_asset_id=asset.id))
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()
