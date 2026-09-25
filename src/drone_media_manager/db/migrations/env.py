"""Alembic environment for the local control-plane schema."""

from __future__ import annotations

from alembic import context
from alembic.util.exc import CommandError

import drone_media_manager.db.models.auth
import drone_media_manager.db.models.catalog
import drone_media_manager.db.models.core
import drone_media_manager.editorial.models
import drone_media_manager.grouping.models
import drone_media_manager.movement.models
import drone_media_manager.scoring.models  # noqa: F401
from drone_media_manager.config import ServerSettings
from drone_media_manager.db.base import Base
from drone_media_manager.db.session import create_engine_from_settings

config = context.config
target_metadata = Base.metadata


def validated_server_settings() -> ServerSettings:
    """Return the validated settings required for a migration connection."""
    settings = config.attributes.get("server_settings")
    if not isinstance(settings, ServerSettings):
        raise CommandError("Migrations require validated ServerSettings")
    return settings


def run_migrations_offline() -> None:
    """Run migrations without a live database connection."""
    engine = create_engine_from_settings(validated_server_settings())
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    try:
        with context.begin_transaction():
            context.run_migrations()
    finally:
        engine.dispose()


def run_migrations_online() -> None:
    """Run migrations against a newly opened local database connection."""
    engine = create_engine_from_settings(validated_server_settings())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
