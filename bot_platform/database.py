"""Database session and engine helpers."""
from __future__ import annotations

from contextlib import asynccontextmanager

from sqlalchemy.engine import URL
from sqlalchemy.engine.url import make_url

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def should_enable_pre_ping(database_url: str) -> bool:
    """Return ``True`` when ``pool_pre_ping`` may be safely enabled for the URL."""

    url: URL = make_url(database_url)
    driver = url.get_driver_name()
    # ``pool_pre_ping`` dla asyncpg kończy się wyjątkiem MissingGreenlet podczas odpytywania
    # puli (https://sqlalche.me/e/20/xd2s). Pozostawiamy tę funkcję wyłączoną dla tego
    # sterownika, a dla pozostałych zachowujemy dotychczasowe zachowanie.
    if driver == "asyncpg":
        return False
    return True


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=should_enable_pre_ping(settings.database_url),
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncSession:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
