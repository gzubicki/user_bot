"""Modele obsługujące zgłoszenia, cytaty i moderację."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import MediaType, ModerationStatus

if TYPE_CHECKING:  # pragma: no cover - dla poprawnych podpowiedzi typów
    from .persona import Persona


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        Index("ix_submission_status", "status"),
        Index("ix_submission_persona", "persona_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    persona_id: Mapped[int] = mapped_column(
        ForeignKey("personas.id", ondelete="CASCADE"), nullable=False
    )
    submitted_by_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    submitted_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    submitted_by_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    submitted_by_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    quoted_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    quoted_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    quoted_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    decided_in_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text)

    persona: Mapped["Persona"] = relationship("Persona")
    moderation_actions: Mapped[list["ModerationAction"]] = relationship(
        "ModerationAction", back_populates="submission"
    )


class Quote(Base):
    __tablename__ = "quotes"
    __table_args__ = (
        Index("ix_quote_persona", "persona_id"),
        Index("ix_quote_language", "language"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    persona_id: Mapped[int] = mapped_column(
        ForeignKey("personas.id", ondelete="CASCADE"), nullable=False
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    source_submission_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True
    )

    persona: Mapped["Persona"] = relationship("Persona")
    source_submission: Mapped[Optional[Submission]] = relationship("Submission")


class ModerationAction(Base):
    __tablename__ = "moderation_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)

    submission: Mapped[Submission] = relationship(
        "Submission", back_populates="moderation_actions"
    )


__all__ = ["Submission", "Quote", "ModerationAction"]
