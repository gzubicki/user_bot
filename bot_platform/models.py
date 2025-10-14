"""SQLAlchemy models describing the domain."""
from __future__ import annotations

import enum
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

Base = declarative_base()


class MediaType(enum.StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"


class ModerationStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SubscriptionPlan(enum.StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"
    FREE = "free"


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_token: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    persona: Mapped["Persona"] = relationship("Persona", back_populates="bots")
    chats: Mapped[list["BotChatSubscription"]] = relationship("BotChatSubscription", back_populates="bot")


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    language: Mapped[str] = mapped_column(String(16), default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    aliases: Mapped[list["PersonaAlias"]] = relationship("PersonaAlias", back_populates="persona")
    bots: Mapped[list[Bot]] = relationship("Bot", back_populates="persona")


class PersonaAlias(Base):
    __tablename__ = "persona_aliases"
    __table_args__ = (
        UniqueConstraint("persona_id", "alias", name="uq_alias_per_persona"),
        Index("ix_alias_lookup", "alias"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    added_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    added_in_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    removed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)
    removed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    removed_in_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    persona: Mapped["Persona"] = relationship("Persona", back_populates="aliases")

class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        Index("ix_submission_status", "status"),
        Index("ix_submission_persona", "persona_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), nullable=False)
    submitted_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    submitted_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[MediaType] = mapped_column(
        Enum(
            MediaType,
            name="mediatype",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
    )
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    file_id: Mapped[Optional[str]] = mapped_column(String(255))
    file_hash: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    status: Mapped[ModerationStatus] = mapped_column(
        Enum(
            ModerationStatus,
            name="moderationstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            validate_strings=True,
        ),
        default=ModerationStatus.PENDING.value,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    decided_in_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)

    persona: Mapped["Persona"] = relationship("Persona")
    moderation_actions: Mapped[list["ModerationAction"]] = relationship("ModerationAction", back_populates="submission")

class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (
        Index("ix_quote_persona", "persona_id"),
        Index("ix_quote_language", "language"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    persona_id: Mapped[int] = mapped_column(ForeignKey("personas.id", ondelete="CASCADE"), nullable=False)
    media_type: Mapped[MediaType] = mapped_column(
        Enum(
            MediaType,
            name="mediatype",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
    )
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    file_id: Mapped[Optional[str]] = mapped_column(String(255))
    file_hash: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    language: Mapped[str] = mapped_column(String(16), default="auto", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    source_submission_id: Mapped[Optional[int]] = mapped_column(ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True)

    persona: Mapped["Persona"] = relationship("Persona")
    source_submission: Mapped[Optional[Submission]] = relationship("Submission")


class ModerationAction(Base):
    __tablename__ = "moderation_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    performed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    admin_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    action: Mapped[ModerationStatus] = mapped_column(
        Enum(
            ModerationStatus,
            name="moderationstatus",
            values_callable=lambda enum_cls: [item.value for item in enum_cls],
            validate_strings=True,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    submission: Mapped["Submission"] = relationship("Submission", back_populates="moderation_actions")

class BotChatSubscription(Base):
    __tablename__ = "bot_chat_subscriptions"
    __table_args__ = (
        UniqueConstraint("bot_id", "chat_id", name="uq_bot_chat"),
        Index("ix_bot_subscription_status", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
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
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    granted_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    granted_in_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    bot: Mapped["Bot"] = relationship("Bot", back_populates="chats")
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
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), nullable=False)
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
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_event_type", "event_type"),
        CheckConstraint("length(event_type) > 0", name="ck_event_type_not_empty"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    actor_user_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    actor_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
