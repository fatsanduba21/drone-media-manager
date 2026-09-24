"""Phase 3A keeps suggested and human-confirmed groups separate."""

from pathlib import Path

from alembic import command
from pydantic import SecretStr
from sqlalchemy import select, text

from drone_media_manager.cli.server import alembic_config
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.models.catalog import AssetFile, CatalogAsset
from drone_media_manager.db.models.core import AuditEvent
from drone_media_manager.db.models.ingest import Trip
from drone_media_manager.db.session import create_engine_from_settings, session_factory
from drone_media_manager.grouping.models import (
    GroupingSuggestion,
    LocationGroup,
    TelemetryTrack,
)
from drone_media_manager.grouping.repository import (
    analyze_trip,
    assign_range,
    ordered_assets,
)


def test_suggestions_do_not_replace_confirmed_group(tmp_path: Path) -> None:
    root = tmp_path / "omv"
    root.mkdir()
    settings = ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=root,
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    with session_factory(engine)() as session:
        trip = Trip(name="Nova viagem", slug="nova", nas_rel_path="nova")
        session.add(trip)
        session.flush()
        for number, lat in [(1, -3.85), (2, -3.8501), (3, -3.9)]:
            stem = f"DJI_{number:04}"
            (root / f"{stem}.srt").write_text(
                f"1\n00:00:00,000 --> 00:00:00,033\n2026-09-01 10:00:00 [latitude: {lat}] [longitude: -32.42]\n"
            )
            asset = CatalogAsset(
                asset_id=f"{number:064x}",
                trip_id=trip.id,
                media_type="VIDEO",
                classification="YOUTUBE_16X9",
                verification_status="VERIFIED",
            )
            session.add(asset)
            session.flush()
            for role, suffix in [("ORIGINAL", "mp4"), ("SRT", "srt")]:
                session.add(
                    AssetFile(
                        catalog_asset_id=asset.id,
                        role=role,
                        rel_path=f"{stem}.{suffix}",
                        sha256="a" * 64,
                        availability_status="AVAILABLE",
                    )
                )
        session.commit()
        assets = ordered_assets(session, trip.id)
        suggestions = analyze_trip(session, settings, trip.id)
        session.commit()
        assert [(s.start_asset_id, s.end_asset_id) for s in suggestions] == [
            (assets[0].id, assets[1].id),
            (assets[2].id, assets[2].id),
        ]
        assert len(session.scalars(select(TelemetryTrack)).all()) == 3
        group = assign_range(session, trip.id, assets[0].id, assets[1].id, name="Praia")
        session.commit()
        assert group.name_final == "Praia"
        analyze_trip(session, settings, trip.id)
        session.commit()
        assert session.get(CatalogAsset, assets[0].id).location_group_id == group.id
        assert session.get(LocationGroup, group.id).name_final == "Praia"
        assert (
            len(
                session.scalars(
                    select(AuditEvent).where(AuditEvent.entity_id == group.id)
                ).all()
            )
            == 1
        )
        assert len(session.scalars(select(GroupingSuggestion)).all()) == 4
        assert (
            len(
                session.scalars(
                    select(GroupingSuggestion).where(
                        GroupingSuggestion.superseded_at.is_(None)
                    )
                ).all()
            )
            == 2
        )
    engine.dispose()


def test_legacy_range_can_be_corrected_without_srt(tmp_path: Path) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    command.upgrade(alembic_config(settings), "head")
    engine = create_engine_from_settings(settings)
    with session_factory(engine)() as session:
        trip = Trip(name="Legado", slug="legado", nas_rel_path="legado")
        session.add(trip)
        session.flush()
        for n in (1, 2, 3):
            asset = CatalogAsset(
                asset_id=f"{n:064x}",
                trip_id=trip.id,
                media_type="PHOTO",
                classification="FOTOS",
                verification_status="VERIFIED",
            )
            session.add(asset)
            session.flush()
            session.add(
                AssetFile(
                    catalog_asset_id=asset.id,
                    role="ORIGINAL",
                    rel_path=f"DJI_{n:04}.JPG",
                    sha256="a" * 64,
                    availability_status="AVAILABLE",
                )
            )
        session.commit()
        assets = ordered_assets(session, trip.id)
        group = assign_range(session, trip.id, assets[0].id, assets[1].id, name="Casa")
        session.commit()
        assign_range(session, trip.id, assets[1].id, assets[2].id, group_id=group.id)
        session.commit()
        assert [
            asset.location_group_id for asset in ordered_assets(session, trip.id)
        ] == [None, group.id, group.id]
        assign_range(session, trip.id, assets[0].id, assets[2].id, group_id=group.id)
        session.commit()
        middle = assign_range(session, trip.id, assets[1].id, assets[1].id, name="Meio")
        session.commit()
        assert [
            asset.location_group_id for asset in ordered_assets(session, trip.id)
        ] == [group.id, middle.id, group.id]
    engine.dispose()


def test_migration_preserves_existing_catalog_assets(tmp_path: Path) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    config = alembic_config(settings)
    command.upgrade(config, "0004_derivatives")
    engine = create_engine_from_settings(settings)
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO trips (id, name, slug, nas_rel_path, created_at, updated_at)
            VALUES ('trip-1', 'Existente', 'existente', 'existente', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """)
        )
        connection.execute(
            text("""
            INSERT INTO catalog_assets (
                id, asset_id, trip_id, media_type, classification, verification_status,
                created_at, updated_at
            ) VALUES (
                'asset-1', :asset_id, 'trip-1', 'PHOTO', 'FOTOS', 'VERIFIED',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """),
            {"asset_id": "a" * 64},
        )
        connection.execute(
            text("""
            INSERT INTO asset_files (
                id, catalog_asset_id, role, rel_path, sha256, availability_status,
                created_at, updated_at
            ) VALUES (
                'file-1', 'asset-1', 'ORIGINAL', 'existente/001.jpg', :sha, 'AVAILABLE',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
        """),
            {"sha": "b" * 64},
        )
        connection.execute(
            text("""
            INSERT INTO derivatives (
                id, catalog_asset_id, kind, status, profile_version, source_sha256,
                updated_at
            ) VALUES (
                'derivative-1', 'asset-1', 'THUMBNAIL', 'READY', 'grid-v1', :sha,
                CURRENT_TIMESTAMP
            )
        """),
            {"sha": "b" * 64},
        )
    engine.dispose()
    command.upgrade(config, "head")
    engine = create_engine_from_settings(settings)
    with session_factory(engine)() as session:
        asset = session.get(CatalogAsset, "asset-1")
        assert asset is not None
        assert asset.asset_id == "a" * 64
        assert asset.location_group_id is None
        assert asset.capture_time is None
    engine.dispose()

    command.downgrade(config, "0004_derivatives")
    engine = create_engine_from_settings(settings)
    with engine.connect() as connection:
        columns = [
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(catalog_assets)")
        ]
        assert "location_group_id" not in columns
        assert (
            connection.exec_driver_sql("SELECT COUNT(*) FROM asset_files").scalar_one()
            == 1
        )
        assert (
            connection.exec_driver_sql("SELECT COUNT(*) FROM derivatives").scalar_one()
            == 1
        )
    engine.dispose()


def test_capture_time_migration_keeps_groups_and_retires_old_suggestions(
    tmp_path: Path,
) -> None:
    settings = ServerSettings(
        database_path=tmp_path / "db.sqlite3",
        omv_root=tmp_path / "omv",
        worker_bootstrap_token=SecretStr("x" * 32),
    )
    config = alembic_config(settings)
    command.upgrade(config, "0007_location_names")
    engine = create_engine_from_settings(settings)
    with engine.begin() as connection:
        connection.execute(
            text("""
            INSERT INTO trips (id, name, slug, nas_rel_path, created_at, updated_at)
            VALUES ('trip-1', 'Viagem', 'viagem', 'viagem', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """)
        )
        connection.execute(
            text("""
            INSERT INTO location_groups (id, trip_id, name_final, name_source, name_locked,
                created_at, updated_at)
            VALUES ('group-1', 'trip-1', 'Praia', 'HUMAN', 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """)
        )
        connection.execute(
            text("""
            INSERT INTO catalog_assets (id, asset_id, trip_id, location_group_id, media_type,
                classification, verification_status, created_at, updated_at)
            VALUES ('asset-1', :asset_id, 'trip-1', 'group-1', 'VIDEO', 'YOUTUBE_16X9',
                'VERIFIED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """),
            {"asset_id": "a" * 64},
        )
        connection.execute(
            text("""
            INSERT INTO grouping_suggestions (id, trip_id, start_asset_id, end_asset_id,
                algorithm_version, evidence_json, created_at)
            VALUES ('suggestion-1', 'trip-1', 'asset-1', 'asset-1', 'grouping-v1', '{}',
                CURRENT_TIMESTAMP)
        """)
        )
    engine.dispose()
    command.upgrade(config, "head")
    engine = create_engine_from_settings(settings)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT location_group_id FROM catalog_assets WHERE id = 'asset-1'"
                )
            ).scalar_one()
            == "group-1"
        )
        assert (
            connection.execute(
                text(
                    "SELECT superseded_at FROM grouping_suggestions WHERE id = 'suggestion-1'"
                )
            ).scalar_one()
            is not None
        )
    engine.dispose()
