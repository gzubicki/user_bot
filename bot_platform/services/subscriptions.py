"""Subscription management primitives."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, Optional

from bot_platform.config import SubscriptionSettings, subscription_settings


class SubscriptionPlan(str, Enum):
    """Enumeration of supported subscription plans."""

    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


@dataclass(slots=True)
class ChatSubscription:
    """Representation of a chat subscription for a single workspace/user."""

    owner_id: str
    plan: SubscriptionPlan
    expires_at: Optional[datetime] = None


class SubscriptionStore:
    """In-memory subscription persistence used for illustration/testing."""

    def __init__(self) -> None:
        self._storage: Dict[str, ChatSubscription] = {}

    def get(self, owner_id: str) -> Optional[ChatSubscription]:
        return self._storage.get(owner_id)

    def save(self, subscription: ChatSubscription) -> None:
        self._storage[subscription.owner_id] = subscription


def _plan_duration(
    plan: SubscriptionPlan, settings: SubscriptionSettings = subscription_settings
) -> Optional[timedelta]:
    """Return the duration associated with a plan, if any."""

    if plan is SubscriptionPlan.FREE:
        days = max(settings.free_plan_period_days, 0)
        return timedelta(days=days)
    return None


def ensure_chat_subscription(
    owner_id: str,
    plan: SubscriptionPlan,
    store: SubscriptionStore,
    *,
    settings: SubscriptionSettings = subscription_settings,
) -> ChatSubscription:
    """Create or update a chat subscription entry with the correct expiry."""

    subscription = store.get(owner_id)
    duration = _plan_duration(plan, settings)
    expires_at: Optional[datetime] = None
    if duration is not None:
        expires_at = datetime.now(timezone.utc) + duration

    if subscription is None:
        subscription = ChatSubscription(owner_id=owner_id, plan=plan, expires_at=expires_at)
    else:
        subscription.plan = plan
        subscription.expires_at = expires_at

    store.save(subscription)
    return subscription
