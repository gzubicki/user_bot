"""Modele dotyczące person i ich tożsamości."""
from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:  # pragma: no cover - tylko dla wskazówek typów
    from .bot import Bot


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, default=None)
    language: Mapped[str] = mapped_column(String(16), default="auto")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    aliases: Mapped[list["PersonaAlias"]] = relationship(
        "PersonaAlias", back_populates="persona"
    )
    identities: Mapped[list["PersonaIdentity"]] = relationship(
        "PersonaIdentity",
        back_populates="persona",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PersonaIdentity.id",
    )
    bots: Mapped[list["Bot"]] = relationship("Bot", back_populates="persona")


class PersonaAlias(Base):
    __tablename__ = "persona_aliases"
    __table_args__ = (
        UniqueConstraint("persona_id", "alias", name="uq_alias_per_persona"),
        Index("ix_alias_lookup", "alias"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    persona_id: Mapped[int] = mapped_column(
        ForeignKey("personas.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    added_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    added_in_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    removed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=None
    )
    removed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    removed_in_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    persona: Mapped["Persona"] = relationship("Persona", back_populates="aliases")


class PersonaIdentity(Base):
    __tablename__ = "persona_identities"
    __table_args__ = (
        CheckConstraint(
            "telegram_user_id IS NOT NULL OR telegram_username IS NOT NULL OR display_name IS NOT NULL",
            name="ck_persona_identity_has_any_identifier",
        ),
        Index("ix_persona_identity_user_id", "telegram_user_id"),
        Index("ix_persona_identity_username", "telegram_username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    persona_id: Mapped[int] = mapped_column(
        ForeignKey("personas.id", ondelete="CASCADE"), nullable=False
    )
    telegram_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    added_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    added_in_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    removed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=None
    )
    removed_by_user_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    removed_in_chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    persona: Mapped["Persona"] = relationship("Persona", back_populates="identities")


__all__ = ["Persona", "PersonaAlias", "PersonaIdentity"]
