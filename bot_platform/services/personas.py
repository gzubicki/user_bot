"""Persona and alias helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Persona, PersonaAlias, PersonaIdentity


@dataclass(slots=True)
class PersonaIdentityStats:
    """Aggregate information about persona identity bindings."""

    persona: Persona
    active_identities: int
    total_identities: int


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


async def list_personas(session: AsyncSession) -> Sequence[Persona]:
    result = await session.execute(select(Persona).order_by(Persona.name.asc()))
    return list(result.scalars().all())


async def list_personas_with_identity_stats(
    session: AsyncSession,
) -> list[PersonaIdentityStats]:
    stmt = (
        select(
            Persona,
            func.count(PersonaIdentity.id).label("total_identities"),
            func.coalesce(
                func.sum(
                    case((PersonaIdentity.removed_at.is_(None), 1), else_=0)
                ),
                0,
            ).label("active_identities"),
        )
        .outerjoin(PersonaIdentity, PersonaIdentity.persona_id == Persona.id)
        .group_by(Persona.id)
        .order_by(Persona.name.asc())
    )
    result = await session.execute(stmt)
    stats: list[PersonaIdentityStats] = []
    for persona, total_identities, active_identities in result.all():
        stats.append(
            PersonaIdentityStats(
                persona=persona,
                active_identities=int(active_identities or 0),
                total_identities=int(total_identities or 0),
            )
        )
    return stats


async def get_persona_by_id(session: AsyncSession, persona_id: int) -> Optional[Persona]:
    result = await session.execute(select(Persona).where(Persona.id == persona_id))
    return result.scalars().first()


async def get_persona_by_name(session: AsyncSession, name: str) -> Optional[Persona]:
    result = await session.execute(select(Persona).where(Persona.name.ilike(name)))
    return result.scalars().first()


async def create_persona(
    session: AsyncSession,
    *,
    name: str,
    description: Optional[str],
    language: str,
) -> Persona:
    existing = await get_persona_by_name(session, name)
    if existing is not None:
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
    return persona


__all__ = [
    "get_persona_by_alias",
    "add_alias",
    "remove_alias",
    "list_persona_aliases",
    "list_personas",
    "list_personas_with_identity_stats",
    "get_persona_by_id",
    "get_persona_by_name",
    "create_persona",
    "PersonaIdentityStats",
]
