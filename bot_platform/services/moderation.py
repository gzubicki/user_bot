"""Moderation workflow utilities."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..logging_config import get_logger
from ..models import (
    MediaType,
    ModerationAction,
    ModerationStatus,
    Persona,
    Submission,
)


logger = get_logger(__name__)


async def list_pending_submissions(
    session: AsyncSession,
    *,
    persona_id: Optional[int] = None,
    limit: Optional[int] = None,
    exclude_ids: Optional[Iterable[int]] = None,
) -> list[Submission]:
    stmt = (
        select(Submission)
        .options(
            selectinload(Submission.persona).selectinload(Persona.identities)
        )
        .where(Submission.status == ModerationStatus.PENDING)
    )
    if persona_id is not None:
        stmt = stmt.where(Submission.persona_id == persona_id)
    if exclude_ids:
        excluded = [int(value) for value in exclude_ids]
        if excluded:
            stmt = stmt.where(~Submission.id.in_(excluded))
    stmt = stmt.order_by(Submission.created_at.asc())
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    submissions = list(result.scalars().all())
    logger.info(
        "Pobrano %s zgłoszeń oczekujących na moderację (persona_id=%s, limit=%s)",
        len(submissions),
        persona_id,
        limit,
    )
    return submissions


async def get_submission_by_id(session: AsyncSession, submission_id: int) -> Optional[Submission]:
    stmt = (
        select(Submission)
        .options(
            selectinload(Submission.persona).selectinload(Persona.identities)
        )
        .where(Submission.id == submission_id)
    )
    result = await session.execute(stmt)
    submission = result.scalars().first()
    if submission is None:
        logger.warning("Nie znaleziono zgłoszenia o ID=%s", submission_id)
    else:
        logger.debug(
            "Odczytano zgłoszenie ID=%s w statusie %s",
            submission.id,
            submission.status,
        )
    return submission


async def create_submission(
    session: AsyncSession,
    *,
    persona_id: int,
    submitted_by_user_id: int,
    submitted_chat_id: int,
    submitted_by_username: Optional[str] = None,
    submitted_by_name: Optional[str] = None,
    media_type: MediaType,
    text_content: Optional[str] = None,
    file_id: Optional[str] = None,
    file_hash: Optional[bytes] = None,
) -> Submission:
    submission = Submission(
        persona_id=persona_id,
        submitted_by_user_id=submitted_by_user_id,
        submitted_chat_id=submitted_chat_id,
        submitted_by_username=submitted_by_username,
        submitted_by_name=submitted_by_name,
        media_type=media_type.value if isinstance(media_type, MediaType) else media_type,
        text_content=text_content,
        file_id=file_id,
        file_hash=file_hash,
        status=ModerationStatus.PENDING.value,
    )
    session.add(submission)
    await session.flush()
    await session.refresh(submission)
    logger.info(
        "Dodano nowe zgłoszenie ID=%s dla persony ID=%s (media_type=%s)",
        submission.id,
        submission.persona_id,
        submission.media_type,
    )
    return submission


async def decide_submission(
    session: AsyncSession,
    submission: Submission,
    *,
    moderator_user_id: Optional[int],
    moderator_chat_id: Optional[int],
    action: ModerationStatus,
    notes: str | None = None,
) -> Submission:
    if action not in {ModerationStatus.APPROVED, ModerationStatus.REJECTED}:
        raise ValueError("Moderation action must be APPROVED or REJECTED")

    submission.status = action.value if isinstance(action, ModerationStatus) else action
    submission.decided_at = datetime.utcnow()
    submission.decided_by_user_id = moderator_user_id
    submission.decided_in_chat_id = moderator_chat_id
    submission.rejection_reason = notes if action == ModerationStatus.REJECTED else None

    moderation_action = ModerationAction(
        submission_id=submission.id,
        performed_by_user_id=moderator_user_id,
        admin_chat_id=moderator_chat_id,
        action=action.value if isinstance(action, ModerationStatus) else action,
        notes=notes,
    )
    session.add(moderation_action)
    await session.flush()
    logger.info(
        "Zaktualizowano status zgłoszenia ID=%s na %s", submission.id, submission.status
    )
    return submission


async def bulk_mark_submissions(
    session: AsyncSession,
    submission_ids: Iterable[int],
    *,
    status: ModerationStatus,
) -> int:
    stmt = (
        update(Submission)
        .where(Submission.id.in_(list(submission_ids)))
        .values(status=status, decided_at=datetime.utcnow())
    )
    result = await session.execute(stmt)
    affected = result.rowcount or 0
    logger.info(
        "Masowo zaktualizowano %s zgłoszeń na status %s", affected, status
    )
    return affected


async def purge_pending_submissions(
    session: AsyncSession, *, persona_id: Optional[int] = None
) -> int:
    """Remove all pending submissions, optionally limited to a persona."""

    stmt = delete(Submission).where(Submission.status == ModerationStatus.PENDING)
    if persona_id is not None:
        stmt = stmt.where(Submission.persona_id == persona_id)
    result = await session.execute(stmt)
    removed = result.rowcount or 0
    logger.warning(
        "Usunięto %s oczekujących zgłoszeń (persona_id=%s)", removed, persona_id
    )
    return removed


async def count_pending_submissions(
    session: AsyncSession, *, persona_id: Optional[int] = None
) -> int:
    stmt = select(func.count()).select_from(Submission).where(
        Submission.status == ModerationStatus.PENDING
    )
    if persona_id is not None:
        stmt = stmt.where(Submission.persona_id == persona_id)
    result = await session.execute(stmt)
    total = int(result.scalar_one() or 0)
    logger.debug(
        "W kolejce oczekuje %s zgłoszeń (persona_id=%s)", total, persona_id
    )
    return total


__all__ = [
    "create_submission",
    "list_pending_submissions",
    "get_submission_by_id",
    "decide_submission",
    "bulk_mark_submissions",
    "purge_pending_submissions",
    "count_pending_submissions",
]
