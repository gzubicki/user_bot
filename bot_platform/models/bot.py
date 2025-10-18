"""Modele związane z botami i subskrypcjami."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import SubscriptionPlan

if TYPE_CHECKING:  # pragma: no cover - pomoc w typowaniu
    from .persona import Persona


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_token: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    persona_id: Mapped[int] = mapped_column(
        ForeignKey("personas.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    persona: Mapped["Persona"] = relationship(
        "Persona", back_populates="bots"
    )
    chats: Mapped[list["BotChatSubscription"]] = relationship(
        "BotChatSubscription", back_populates="bot"
    )


class BotChatSubscription(Base):
    __tablename__ = "bot_chat_subscriptions"
    __table_args__ = (
        UniqueConstraint("bot_id", "chat_id", name="uq_bot_chat"),
        Index("ix_bot_subscription_status", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(
            SubscriptionPlan,
            name="subscriptionplan",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    granted_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    granted_in_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    bot: Mapped["Bot"] = relationship(
        "Bot", back_populates="chats"
    )

    @property
    def remaining_time(self) -> Optional[timedelta]:
        if self.expires_at is None:
            return None
        return self.expires_at - datetime.utcnow()


class SubscriptionLedger(Base):
    __tablename__ = "subscription_ledger"
    __table_args__ = (
        Index("ix_subscription_ledger_bot", "bot_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), nullable=False
    )
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    plan: Mapped[SubscriptionPlan] = mapped_column(
        Enum(
            SubscriptionPlan,
            name="subscriptionplan",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
    )
    amount_stars: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(255))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)


__all__ = ["Bot", "BotChatSubscription", "SubscriptionLedger"]
