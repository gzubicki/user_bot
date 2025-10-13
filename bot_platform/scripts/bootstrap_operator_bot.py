"""Skrypt bootstrapujący pierwszego bota operatorskiego w bazie.

Uruchomienie w środowisku Docker Compose:

```
docker compose run --rm app python -m bot_platform.scripts.bootstrap_operator_bot <TOKEN>
```
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bot_platform.database import get_session_factory
from bot_platform.models import Bot, Persona


def _hash_token(token: str) -> str:
    """Zwraca hash SHA-512 dla przekazanego tokena."""

    return hashlib.sha512(token.encode()).hexdigest()


async def _ensure_persona(session: AsyncSession, persona_name: str, language: str) -> Persona:
    """Zwróć istniejącą personę lub utwórz nową."""

    result = await session.execute(select(Persona).where(Persona.name == persona_name))
    persona = result.scalar_one_or_none()
    if persona is not None:
        if not persona.is_active:
            persona.is_active = True
        return persona

    persona = Persona(
        name=persona_name,
        description="Persona operatorska",
        language=language,
        created_at=datetime.utcnow(),
        is_active=True,
    )
    session.add(persona)
    await session.flush()
    return persona


async def _bootstrap(token: str, display_name: str, persona_name: str, language: str) -> None:
    """Dodaj bota operatorskiego i związaną personę."""

    session_factory = get_session_factory()
    async with session_factory() as session:
        persona = await _ensure_persona(session, persona_name, language)

        stmt = (
            insert(Bot)
            .values(
                api_token=token,
                token_hash=_hash_token(token),
                display_name=display_name,
                persona_id=persona.id,
                created_at=datetime.utcnow(),
                is_active=True,
            )
            .on_conflict_do_update(
                index_elements=[Bot.token_hash],
                set_={
                    "api_token": token,
                    "display_name": display_name,
                    "persona_id": persona.id,
                    "is_active": True,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap pierwszego bota operatorskiego.")
    parser.add_argument("token", help="Token bota wygenerowany przez @BotFather.")
    parser.add_argument(
        "--display-name",
        default="Bot operatorski",
        help="Przyjazna nazwa wyświetlana w panelu.",
    )
    parser.add_argument(
        "--persona-name",
        default="Persona operatorska",
        help="Nazwa persony przypisanej do bota.",
    )
    parser.add_argument(
        "--language",
        default="pl",
        help="Kod języka persony (np. pl, en).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    asyncio.run(_bootstrap(args.token.strip(), args.display_name, args.persona_name, args.language))


if __name__ == "__main__":
    main()
