"""Persona and alias helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Persona, PersonaAlias


async def get_persona_by_alias(session: AsyncSession, alias: str) -> Optional[Persona]:
    stmt = (
        select(Persona)
        .join(Persona.aliases)
        .where(PersonaAlias.alias.ilike(alias))
        .where(PersonaAlias.removed_at.is_(None))
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def add_alias(
    session: AsyncSession,
    persona: Persona,
    alias: str,
    *,
    admin_user_id: Optional[int],
    admin_chat_id: Optional[int],
) -> PersonaAlias:
    existing = (
        await session.execute(
            select(PersonaAlias).where(
                PersonaAlias.persona_id == persona.id, PersonaAlias.alias.ilike(alias)
            )
        )
    ).scalars().first()
    if existing and existing.removed_at is None:
        return existing

    alias_record = existing or PersonaAlias(persona_id=persona.id, alias=alias)
    alias_record.added_by_user_id = admin_user_id
    alias_record.added_in_chat_id = admin_chat_id
    alias_record.added_at = datetime.utcnow()
    alias_record.removed_at = None
    alias_record.removed_by_user_id = None
    alias_record.removed_in_chat_id = None
    session.add(alias_record)
    await session.flush()
    return alias_record


async def remove_alias(
    session: AsyncSession,
    alias_record: PersonaAlias,
    *,
    admin_user_id: Optional[int],
    admin_chat_id: Optional[int],
) -> PersonaAlias:
    alias_record.removed_at = datetime.utcnow()
    alias_record.removed_by_user_id = admin_user_id
    alias_record.removed_in_chat_id = admin_chat_id
    await session.flush()
    return alias_record


async def list_persona_aliases(session: AsyncSession, persona: Persona) -> list[PersonaAlias]:
    stmt = select(PersonaAlias).where(PersonaAlias.persona_id == persona.id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


__all__ = [
    "get_persona_by_alias",
    "add_alias",
    "remove_alias",
    "list_persona_aliases",
]
