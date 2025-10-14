"""Obsługa tokenów botów przechowywanych w bazie danych."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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


def _hash_token(token: str) -> str:
    return hashlib.sha512(token.encode()).hexdigest()


async def count_bots(session: AsyncSession) -> int:
    result = await session.execute(select(func.count(Bot.id)))
    return int(result.scalar_one())


class BotLimitExceededError(Exception):
    """Podnoszone, gdy osiągnięto limit liczby botów."""


class BotTokenInUseError(Exception):
    """Podnoszone, gdy nowy token koliduje z istniejącym botem."""


async def upsert_bot(
    session: AsyncSession,
    *,
    token: str,
    display_name: str,
    persona_id: int,
) -> Tuple[Bot, bool]:
    """Dodaj nowego bota lub zaktualizuj istniejącego.

    Zwraca krotkę (bot, created), gdzie created informuje czy rekord był nowy.
    """

    token_hash = _hash_token(token)
    existing_bot = (
        await session.execute(select(Bot).where(Bot.token_hash == token_hash))
    ).scalars().first()

    created = False
    if existing_bot is None:
        total = await count_bots(session)
        from ..config import get_settings

        max_allowed = get_settings().rate_limits.max_bots_total
        if total >= max_allowed:
            raise BotLimitExceededError(f"Limit {max_allowed} botów został osiągnięty.")

        bot = Bot(
            api_token=token,
            token_hash=token_hash,
            display_name=display_name,
            persona_id=persona_id,
            created_at=datetime.utcnow(),
            is_active=True,
        )
        session.add(bot)
        created = True
    else:
        bot = existing_bot
        bot.api_token = token
        bot.token_hash = token_hash
        bot.display_name = display_name
        bot.persona_id = persona_id
        bot.is_active = True

    await session.flush()
    return bot, created


async def list_bots(session: AsyncSession) -> Iterable[Bot]:
    stmt = select(Bot).options(selectinload(Bot.persona)).order_by(Bot.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_bot_by_id(session: AsyncSession, bot_id: int) -> Optional[Bot]:
    stmt = select(Bot).options(selectinload(Bot.persona)).where(Bot.id == bot_id)
    result = await session.execute(stmt)
    return result.scalars().first()


async def update_bot(
    session: AsyncSession,
    bot: Bot,
    *,
    token: Optional[str] = None,
    display_name: Optional[str] = None,
    persona_id: Optional[int] = None,
) -> Bot:
    if token is not None:
        token_hash = _hash_token(token)
        duplicate = (
            await session.execute(
                select(Bot).where(Bot.token_hash == token_hash, Bot.id != bot.id)
            )
        ).scalars().first()
        if duplicate is not None:
            raise BotTokenInUseError("Token jest już w użyciu przez innego bota.")
        bot.api_token = token
        bot.token_hash = token_hash

    if display_name is not None:
        bot.display_name = display_name

    if persona_id is not None:
        bot.persona_id = persona_id

    bot.is_active = True
    await session.flush()
    return bot


__all__ = [
    "ActiveBotToken",
    "get_active_bot_tokens",
    "get_bot_by_token",
    "refresh_bot_token_cache",
    "count_bots",
    "upsert_bot",
    "get_bot_by_id",
    "BotLimitExceededError",
    "BotTokenInUseError",
    "list_bots",
    "update_bot",
]
