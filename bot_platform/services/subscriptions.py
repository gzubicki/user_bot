"""Subscription management helpers."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..logging_config import get_logger
from ..models import Bot, BotChatSubscription, SubscriptionLedger, SubscriptionPlan


logger = get_logger(__name__)


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
        logger.info(
            "Aktywowano nową subskrypcję czatu %s dla bota ID=%s w planie %s",
            chat_id,
            bot.id,
            plan.value,
        )
    else:
        subscription.plan = plan
        subscription.started_at = datetime.utcnow()
        subscription.expires_at = expires_at
        subscription.is_active = True
        subscription.granted_by_user_id = granted_by_user_id
        subscription.granted_in_chat_id = granted_in_chat_id
        logger.info(
            "Odnowiono subskrypcję czatu %s dla bota ID=%s (plan=%s)",
            chat_id,
            bot.id,
            plan.value,
        )

    ledger_entry = SubscriptionLedger(
        bot_id=bot.id,
        chat_id=chat_id,
        plan=plan,
        amount_stars=amount_stars or 0,
        transaction_id=transaction_id,
    )
    session.add(ledger_entry)
    await session.flush()
    logger.debug(
        "Dodano wpis w dzienniku subskrypcji dla bota ID=%s, czatu %s", bot.id, chat_id
    )
    return subscription


async def deactivate_subscription(session: AsyncSession, subscription: BotChatSubscription) -> BotChatSubscription:
    subscription.is_active = False
    subscription.expires_at = datetime.utcnow()
    await session.flush()
    logger.info(
        "Dezaktywowano subskrypcję ID=%s dla czatu %s", subscription.id, subscription.chat_id
    )
    return subscription


async def list_active_subscriptions(session: AsyncSession, bot: Bot) -> list[BotChatSubscription]:
    stmt = select(BotChatSubscription).where(
        BotChatSubscription.bot_id == bot.id,
        BotChatSubscription.is_active.is_(True),
    )
    result = await session.execute(stmt)
    subscriptions = list(result.scalars().all())
    logger.debug(
        "Bot ID=%s ma %s aktywnych subskrypcji", bot.id, len(subscriptions)
    )
    return subscriptions


__all__ = [
    "ensure_chat_subscription",
    "deactivate_subscription",
    "list_active_subscriptions",
]
