"""SQLite engine and session factory creation."""

from __future__ import annotations

import sqlite3
from typing import cast

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from drone_media_manager.config import ServerSettings


def create_engine_from_settings(settings: ServerSettings) -> Engine:
    """Create a local SQLite engine after ``ServerSettings`` safety validation."""
    database_path = settings.database_path.expanduser().resolve(strict=False)
    database_url = URL.create("sqlite", database=database_path.as_posix())
    engine = create_engine(database_url)

    @event.listens_for(engine, "connect")
    def configure_sqlite_connection(dbapi_connection: object, _: object) -> None:
        sqlite_connection = cast(sqlite3.Connection, dbapi_connection)
        cursor = sqlite_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        finally:
            cursor.close()

    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return sessions that retain loaded values after each commit."""
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
