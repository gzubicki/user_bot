"""Quote management helpers."""
from __future__ import annotations

from datetime import datetime
from random import choice
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import MediaType, Persona, Quote, Submission


async def count_quotes(session: AsyncSession, persona: Persona) -> int:
    result = await session.execute(
        select(func.count(Quote.id)).where(Quote.persona_id == persona.id)
    )
    return int(result.scalar_one())


async def random_quote(session: AsyncSession, persona: Persona) -> Optional[Quote]:
    stmt = select(Quote).where(Quote.persona_id == persona.id).order_by(func.random()).limit(1)
    result = await session.execute(stmt)
    return result.scalars().first()


async def find_quotes_by_language(
    session: AsyncSession,
    persona: Persona,
    *,
    language: Optional[str] = None,
    limit: int = 5,
) -> list[Quote]:
    stmt = select(Quote).where(Quote.persona_id == persona.id)
    if language:
        stmt = stmt.where(Quote.language == language)
    stmt = stmt.order_by(Quote.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def choose_best_quote(candidates: Iterable[Quote]) -> Optional[Quote]:
    candidates = list(candidates)
    if not candidates:
        return None
    return choice(candidates)


async def create_quote_from_submission(
    session: AsyncSession,
    submission: Submission,
    *,
    override_language: Optional[str] = None,
) -> Quote:
    """Create a quote from a moderated submission."""

    language = override_language
    if language is None and submission.persona is not None:
        language = submission.persona.language
    if not language:
        language = "auto"

    quote = Quote(
        persona_id=submission.persona_id,
        media_type=submission.media_type,
        text_content=submission.text_content,
        file_id=submission.file_id,
        file_hash=submission.file_hash,
        language=language,
        created_at=datetime.utcnow(),
        source_submission_id=submission.id,
    )
    session.add(quote)
    await session.flush()
    return quote


__all__ = [
    "count_quotes",
    "random_quote",
    "find_quotes_by_language",
    "choose_best_quote",
    "create_quote_from_submission",
]
