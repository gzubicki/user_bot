"""Moderation workflow utilities."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import ModerationAction, ModerationStatus, Submission


async def list_pending_submissions(session: AsyncSession, *, persona_id: Optional[int] = None) -> list[Submission]:
    stmt = select(Submission).where(Submission.status == ModerationStatus.PENDING)
    if persona_id is not None:
        stmt = stmt.where(Submission.persona_id == persona_id)
    stmt = stmt.order_by(Submission.created_at.asc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def decide_submission(
    session: AsyncSession,
    submission: Submission,
    *,
    admin_id: Optional[int],
    action: ModerationStatus,
    notes: str | None = None,
) -> Submission:
    if action not in {ModerationStatus.APPROVED, ModerationStatus.REJECTED}:
        raise ValueError("Moderation action must be APPROVED or REJECTED")

    submission.status = action
    submission.decided_at = datetime.utcnow()
    submission.decided_by_admin_id = admin_id
    submission.rejection_reason = notes if action == ModerationStatus.REJECTED else None

    moderation_action = ModerationAction(
        submission_id=submission.id,
        admin_id=admin_id,
        action=action,
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
    "list_pending_submissions",
    "decide_submission",
    "bulk_mark_submissions",
]
