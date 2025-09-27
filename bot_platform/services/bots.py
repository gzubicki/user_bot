"""Obsługa tokenów botów przechowywanych w bazie danych."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict

from sqlalchemy import select

from ..database import get_session
from ..models import Bot


@dataclass(slots=True, frozen=True)
class ActiveBotToken:
    """Udostępnia podstawowe informacje o aktywnym bocie."""

    bot_id: int
    token: str
    display_name: str


_TOKEN_CACHE: Dict[str, ActiveBotToken] = {}
_CACHE_EXPIRATION: datetime | None = None
_CACHE_TTL = timedelta(seconds=60)


async def _load_tokens_from_db() -> Dict[str, ActiveBotToken]:
    async with get_session() as session:
        result = await session.execute(
            select(Bot.id, Bot.api_token, Bot.display_name).where(Bot.is_active.is_(True))
        )
        rows = result.all()
    tokens: Dict[str, ActiveBotToken] = {}
    for bot_id, api_token, display_name in rows:
        if api_token:
            tokens[api_token] = ActiveBotToken(
                bot_id=bot_id, token=api_token, display_name=display_name
            )
    return tokens


async def get_active_bot_tokens(force_refresh: bool = False) -> Dict[str, ActiveBotToken]:
    """Zwraca aktualnie aktywne tokeny botów, korzystając z lokalnego cache."""

    global _TOKEN_CACHE, _CACHE_EXPIRATION

    now = datetime.utcnow()
    if (
        not force_refresh
        and _CACHE_EXPIRATION is not None
        and _CACHE_EXPIRATION > now
    ):
        return _TOKEN_CACHE

    _TOKEN_CACHE = await _load_tokens_from_db()
    _CACHE_EXPIRATION = now + _CACHE_TTL
    return _TOKEN_CACHE


async def get_bot_by_token(token: str) -> ActiveBotToken | None:
    """Zwraca informacje o bocie powiązanym z tokenem lub ``None``."""

    tokens = await get_active_bot_tokens()
    bot = tokens.get(token)
    if bot is not None:
        return bot

    tokens = await get_active_bot_tokens(force_refresh=True)
    return tokens.get(token)


async def refresh_bot_token_cache() -> Dict[str, ActiveBotToken]:
    """Czyści cache i ponownie ładuje tokeny z bazy danych."""

    return await get_active_bot_tokens(force_refresh=True)


__all__ = [
    "ActiveBotToken",
    "get_active_bot_tokens",
    "get_bot_by_token",
    "refresh_bot_token_cache",
]
