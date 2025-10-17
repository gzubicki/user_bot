"""Persona and alias helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_config import get_logger
from ..models import Persona, PersonaAlias


logger = get_logger(__name__)


async def get_persona_by_alias(session: AsyncSession, alias: str) -> Optional[Persona]:
    stmt = (
        select(Persona)
        .join(Persona.aliases)
        .where(PersonaAlias.alias.ilike(alias))
        .where(PersonaAlias.removed_at.is_(None))
    )
    result = await session.execute(stmt)
    persona = result.scalars().first()
    if persona is None:
        logger.debug("Alias '%s' nie został powiązany z żadną personą", alias)
    else:
        logger.info("Alias '%s' wskazuje na personę ID=%s", alias, persona.id)
    return persona


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
        logger.debug("Alias '%s' już istnieje i jest aktywny dla persony ID=%s", alias, persona.id)
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
    logger.info("Dodano alias '%s' dla persony ID=%s", alias, persona.id)
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
    logger.info("Usunięto alias '%s' (ID=%s) dla persony ID=%s", alias_record.alias, alias_record.id, alias_record.persona_id)
    return alias_record


async def list_persona_aliases(session: AsyncSession, persona: Persona) -> list[PersonaAlias]:
    stmt = select(PersonaAlias).where(PersonaAlias.persona_id == persona.id)
    result = await session.execute(stmt)
    aliases = list(result.scalars().all())
    logger.info("Pobrano %s aliasów dla persony ID=%s", len(aliases), persona.id)
    return aliases


async def list_personas(session: AsyncSession) -> Sequence[Persona]:
    result = await session.execute(select(Persona).order_by(Persona.name.asc()))
    personas = list(result.scalars().all())
    logger.info("Załadowano %s person", len(personas))
    return personas


async def get_persona_by_id(session: AsyncSession, persona_id: int) -> Optional[Persona]:
    result = await session.execute(select(Persona).where(Persona.id == persona_id))
    persona = result.scalars().first()
    if persona is None:
        logger.warning("Nie znaleziono persony o ID=%s", persona_id)
    else:
        logger.debug("Znaleziono personę ID=%s (%s)", persona.id, persona.name)
    return persona


async def get_persona_by_name(session: AsyncSession, name: str) -> Optional[Persona]:
    result = await session.execute(select(Persona).where(Persona.name.ilike(name)))
    persona = result.scalars().first()
    if persona is None:
        logger.debug("Nie znaleziono persony o nazwie '%s'", name)
    else:
        logger.debug("Znaleziono personę '%s' (ID=%s)", persona.name, persona.id)
    return persona


async def create_persona(
    session: AsyncSession,
    *,
    name: str,
    description: Optional[str],
    language: str,
) -> Persona:
    existing = await get_persona_by_name(session, name)
    if existing is not None:
        logger.info("Persona '%s' już istnieje (ID=%s) – pomijam tworzenie", name, existing.id)
        return existing

    persona = Persona(
        name=name,
        description=description,
        language=language,
        created_at=datetime.utcnow(),
        is_active=True,
    )
    session.add(persona)
    await session.flush()
    logger.info(
        "Utworzono nową personę '%s' (ID=%s, język=%s)", persona.name, persona.id, persona.language
    )
    return persona


__all__ = [
    "get_persona_by_alias",
    "add_alias",
    "remove_alias",
    "list_persona_aliases",
    "list_personas",
    "get_persona_by_id",
    "get_persona_by_name",
    "create_persona",
]
