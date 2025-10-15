"""Testy logiki decydującej o użyciu ``pool_pre_ping``."""
from __future__ import annotations

import pytest

from bot_platform.database import should_enable_pre_ping


@pytest.mark.parametrize(
    "database_url, expected",
    [
        ("postgresql+asyncpg://user:pass@localhost/db", False),
        ("postgresql+psycopg://user:pass@localhost/db", True),
        ("sqlite+aiosqlite:///./test.db", True),
    ],
)
def test_should_enable_pre_ping(database_url: str, expected: bool) -> None:
    """Zapewniamy, że pingi są wyłączane tylko dla asyncpg."""

    assert should_enable_pre_ping(database_url) is expected
