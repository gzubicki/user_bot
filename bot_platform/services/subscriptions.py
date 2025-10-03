"""Subscription management helpers."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import Bot, BotChatSubscription, SubscriptionLedger, SubscriptionPlan


def _plan_duration(plan: SubscriptionPlan) -> Optional[timedelta]:
    settings = get_settings().subscription
    if plan == SubscriptionPlan.MONTHLY:
        return timedelta(days=settings.extra_chat_period_days)
    if plan == SubscriptionPlan.YEARLY:
        return timedelta(days=settings.yearly_period_days)
    return None


async def ensure_chat_subscription(
    session: AsyncSession,
    bot: Bot,
    chat_id: int,
    *,
    plan: SubscriptionPlan,
    granted_by_user_id: Optional[int] = None,
    granted_in_chat_id: Optional[int] = None,
    transaction_id: Optional[str] = None,
    amount_stars: Optional[int] = None,
) -> BotChatSubscription:
    stmt = select(BotChatSubscription).where(
        BotChatSubscription.bot_id == bot.id, BotChatSubscription.chat_id == chat_id
    )
    subscription = (await session.execute(stmt)).scalars().first()

    duration = _plan_duration(plan)
    expires_at = None if duration is None else datetime.utcnow() + duration

    if subscription is None:
        subscription = BotChatSubscription(
            bot_id=bot.id,
            chat_id=chat_id,
            plan=plan,
            started_at=datetime.utcnow(),
            expires_at=expires_at,
            is_active=True,
            granted_by_user_id=granted_by_user_id,
            granted_in_chat_id=granted_in_chat_id,
        )
        session.add(subscription)
    else:
        subscription.plan = plan
        subscription.started_at = datetime.utcnow()
        subscription.expires_at = expires_at
        subscription.is_active = True
        subscription.granted_by_user_id = granted_by_user_id
        subscription.granted_in_chat_id = granted_in_chat_id

    ledger_entry = SubscriptionLedger(
        bot_id=bot.id,
        chat_id=chat_id,
        plan=plan,
        amount_stars=amount_stars or 0,
        transaction_id=transaction_id,
    )
    session.add(ledger_entry)
    await session.flush()
    return subscription


async def deactivate_subscription(session: AsyncSession, subscription: BotChatSubscription) -> BotChatSubscription:
    subscription.is_active = False
    subscription.expires_at = datetime.utcnow()
    await session.flush()
    return subscription


async def list_active_subscriptions(session: AsyncSession, bot: Bot) -> list[BotChatSubscription]:
    stmt = select(BotChatSubscription).where(
        BotChatSubscription.bot_id == bot.id,
        BotChatSubscription.is_active.is_(True),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


__all__ = [
    "ensure_chat_subscription",
    "deactivate_subscription",
    "list_active_subscriptions",
]
