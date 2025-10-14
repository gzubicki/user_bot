"""Konfiguracja środowiska migracji Alembic."""
from __future__ import annotations

import asyncio
import os
from configparser import ConfigParser
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from bot_platform.models import Base

# Alembic Config object, dostępny w pliku ini.
config = context.config

if config.config_file_name is not None:
    parser = ConfigParser()
    parser.read(config.config_file_name)
    if (
        parser.has_section("loggers")
        and parser.has_section("handlers")
        and parser.has_section("formatters")
    ):
        fileConfig(config.config_file_name)

# Metadane modeli, wykorzystywane w trybie autogeneracji.
target_metadata = Base.metadata


def _get_sqlalchemy_url() -> str:
    """Zwraca adres bazy danych z konfiguracji lub zmiennej środowiskowej."""
    url = config.get_main_option("sqlalchemy.url")
    if not url or url == "${DATABASE_URL}":
        env_url = os.getenv("DATABASE_URL")
        if not env_url:
            env_url = os.getenv("USER_BOT_DATABASE_URL")
        if not env_url:
            raise RuntimeError(
                "Brak konfiguracji bazy danych: ustaw zmienną środowiskową DATABASE_URL lub USER_BOT_DATABASE_URL."
            )
        url = env_url
    return url


def run_migrations_offline() -> None:
    """Wykonuje migracje w trybie offline."""
    url = _get_sqlalchemy_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Wykonuje migracje w trybie online z użyciem asynchronicznego silnika."""
    # Build dedicated engine for migrations to avoid loading full application settings.
    database_url = _get_sqlalchemy_url()
    connectable: AsyncEngine = create_async_engine(database_url, pool_pre_ping=True)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
