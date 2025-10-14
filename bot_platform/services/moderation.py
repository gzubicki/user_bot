"""Moderation workflow utilities."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import MediaType, ModerationAction, ModerationStatus, Submission


async def list_pending_submissions(session: AsyncSession, *, persona_id: Optional[int] = None) -> list[Submission]:
    stmt = (
        select(Submission)
        .options(
            selectinload(Submission.persona).selectinload("identities")
        )
        .where(Submission.status == ModerationStatus.PENDING)
    )
    if persona_id is not None:
        stmt = stmt.where(Submission.persona_id == persona_id)
    stmt = stmt.order_by(Submission.created_at.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_submission_by_id(session: AsyncSession, submission_id: int) -> Optional[Submission]:
    stmt = (
        select(Submission)
        .options(
            selectinload(Submission.persona).selectinload("identities")
        )
        .where(Submission.id == submission_id)
    )
    result = await session.execute(stmt)
    return result.scalars().first()


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
    return result.rowcount or 0


__all__ = [
    "create_submission",
    "list_pending_submissions",
    "get_submission_by_id",
    "decide_submission",
    "bulk_mark_submissions",
]
