"""Helpers related to persona identity management and verification."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..logging_config import get_logger
from ..models import Persona, PersonaIdentity, Submission


logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class IdentityDescriptor:
    """Lightweight view of a persona identity record."""

    id: int
    persona_id: int
    telegram_user_id: Optional[int]
    telegram_username: Optional[str]
    display_name: Optional[str]
    active: bool


@dataclass(slots=True, frozen=True)
class IdentityMatchResult:
    """Outcome of comparing a submission author with known persona identities."""

    matched: bool
    matched_identity: Optional[IdentityDescriptor]
    matched_fields: tuple[str, ...]
    candidate_user_id: Optional[int]
    candidate_username: Optional[str]
    candidate_display_name: Optional[str]
    descriptors: tuple[IdentityDescriptor, ...]
    partial_matches: tuple[tuple[IdentityDescriptor, tuple[str, ...]], ...]


def _normalise_username(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = value.strip()
    if candidate.startswith("@"):
        candidate = candidate[1:]
    candidate = candidate.lower()
    return candidate or None


def _normalise_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = re.sub(r"\s+", " ", value).strip().lower()
    return candidate or None


def _to_descriptor(identity: PersonaIdentity) -> IdentityDescriptor:
    return IdentityDescriptor(
        id=identity.id,
        persona_id=identity.persona_id,
        telegram_user_id=identity.telegram_user_id,
        telegram_username=identity.telegram_username,
        display_name=identity.display_name,
        active=identity.removed_at is None,
    )


def describe_identity(identity: IdentityDescriptor | PersonaIdentity) -> str:
    """Return a human-readable summary of an identity record or descriptor."""

    descriptor = identity if isinstance(identity, IdentityDescriptor) else _to_descriptor(identity)

    parts: list[str] = []
    if descriptor.telegram_user_id is not None:
        parts.append(f"ID {descriptor.telegram_user_id}")
    if descriptor.telegram_username:
        username = descriptor.telegram_username
        if not username.startswith("@"):
            username = f"@{username}"
        parts.append(username)
    if descriptor.display_name:
        parts.append(descriptor.display_name)
    if not parts:
        parts.append(f"rekord #{descriptor.id}")
    return ", ".join(parts)


def collect_identity_descriptors(persona: Optional[Persona]) -> tuple[IdentityDescriptor, ...]:
    """Extract descriptors for active identities assigned to a persona."""

    if persona is None:
        return tuple()
    identities = getattr(persona, "identities", None) or []
    active = [identity for identity in identities if identity.removed_at is None]
    descriptors = tuple(_to_descriptor(identity) for identity in active)
    logger.debug(
        "Zebrano %s aktywnych tożsamości dla persony ID=%s",
        len(descriptors),
        getattr(persona, "id", None),
    )
    return descriptors


def _match_descriptor(
    descriptor: IdentityDescriptor,
    *,
    candidate_user_id: Optional[int],
    candidate_username: Optional[str],
    candidate_display_name: Optional[str],
) -> tuple[bool, tuple[str, ...]]:
    matched_fields: list[str] = []

    if descriptor.telegram_user_id is not None:
        if descriptor.telegram_user_id == candidate_user_id:
            matched_fields.append("id")
        else:
            return False, tuple()

    if descriptor.telegram_username:
        expected_username = _normalise_username(descriptor.telegram_username)
        if expected_username and expected_username == candidate_username:
            matched_fields.append("alias")
        else:
            return False, tuple()

    if descriptor.display_name:
        expected_name = _normalise_name(descriptor.display_name)
        if expected_name and expected_name == candidate_display_name:
            matched_fields.append("name")
        else:
            return False, tuple()

    if not matched_fields and not any(
        (
            descriptor.telegram_user_id,
            descriptor.telegram_username,
            descriptor.display_name,
        )
    ):
        # Guard against empty descriptors.
        return False, tuple()

    return True, tuple(matched_fields)


def evaluate_submission_identity(submission: Submission) -> IdentityMatchResult:
    """Compare submission author metadata with persona identity records."""

    quoted_user_id = getattr(submission, "quoted_user_id", None)
    quoted_username = getattr(submission, "quoted_username", None)
    quoted_name = getattr(submission, "quoted_name", None)

    if quoted_user_id is not None or quoted_username or quoted_name:
        candidate_user_id = quoted_user_id
        candidate_username = _normalise_username(quoted_username)
        candidate_display_name = _normalise_name(quoted_name)
    else:
        candidate_user_id = getattr(submission, "submitted_by_user_id", None)
        candidate_username = _normalise_username(getattr(submission, "submitted_by_username", None))
        candidate_display_name = _normalise_name(getattr(submission, "submitted_by_name", None))

    persona = submission.__dict__.get("persona")
    descriptors = collect_identity_descriptors(persona)
    partial_matches: list[tuple[IdentityDescriptor, tuple[str, ...]]] = []

    logger.debug(
        "Weryfikuję zgłoszenie ID=%s z użytkownikiem id=%s alias=%s",
        getattr(submission, "id", None),
        candidate_user_id,
        candidate_username,
    )

    for descriptor in descriptors:
        matched, matched_fields = _match_descriptor(
            descriptor,
            candidate_user_id=candidate_user_id,
            candidate_username=candidate_username,
            candidate_display_name=candidate_display_name,
        )
        if matched:
            logger.info(
                "Zgłoszenie ID=%s pasuje do tożsamości ID=%s po polach %s",
                getattr(submission, "id", None),
                descriptor.id,
                ",".join(matched_fields),
            )
            return IdentityMatchResult(
                matched=True,
                matched_identity=descriptor,
                matched_fields=matched_fields,
                candidate_user_id=candidate_user_id,
                candidate_username=candidate_username,
                candidate_display_name=candidate_display_name,
                descriptors=descriptors,
                partial_matches=tuple(partial_matches),
            )

        # Collect partial matches (e.g. matching alias but missing ID) to aid reviewers.
        partial_fields: list[str] = []
        if descriptor.telegram_user_id is not None and descriptor.telegram_user_id == candidate_user_id:
            partial_fields.append("id")
        if descriptor.telegram_username:
            expected_username = _normalise_username(descriptor.telegram_username)
            if expected_username and expected_username == candidate_username:
                partial_fields.append("alias")
        if descriptor.display_name:
            expected_name = _normalise_name(descriptor.display_name)
            if expected_name and expected_name == candidate_display_name:
                partial_fields.append("name")
        if partial_fields:
            partial_matches.append((descriptor, tuple(partial_fields)))

    result = IdentityMatchResult(
        matched=False,
        matched_identity=None,
        matched_fields=tuple(),
        candidate_user_id=candidate_user_id,
        candidate_username=candidate_username,
        candidate_display_name=candidate_display_name,
        descriptors=descriptors,
        partial_matches=tuple(partial_matches),
    )
    logger.debug(
        "Zgłoszenie ID=%s nie dopasowało żadnej tożsamości (partial=%s)",
        getattr(submission, "id", None),
        len(result.partial_matches),
    )
    return result


def _sanitize_username(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = value.strip()
    if candidate.startswith("@"):
        candidate = candidate[1:]
    candidate = candidate.strip()
    return candidate or None


def _sanitize_display_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = re.sub(r"\s+", " ", value).strip()
    return candidate or None


def _prepare_identity_query(persona: Persona, include_removed: bool):
    stmt = select(PersonaIdentity).where(PersonaIdentity.persona_id == persona.id)
    if not include_removed:
        stmt = stmt.where(PersonaIdentity.removed_at.is_(None))
    order_clause = case((PersonaIdentity.removed_at.is_(None), 0), else_=1)
    stmt = stmt.order_by(order_clause, PersonaIdentity.id.asc())
    return stmt


async def list_persona_identities(
    session: AsyncSession,
    persona: Persona,
    *,
    include_removed: bool = False,
) -> list[PersonaIdentity]:
    stmt = _prepare_identity_query(persona, include_removed)
    result = await session.execute(stmt)
    identities = list(result.scalars().all())
    logger.info(
        "Pobrano %s tożsamości dla persony ID=%s (uwzględniono usunięte=%s)",
        len(identities),
        persona.id,
        include_removed,
    )
    return identities


async def get_identity_by_id(session: AsyncSession, identity_id: int) -> Optional[PersonaIdentity]:
    result = await session.execute(
        select(PersonaIdentity).where(PersonaIdentity.id == identity_id)
    )
    identity = result.scalars().first()
    if identity is None:
        logger.warning("Nie znaleziono tożsamości o ID=%s", identity_id)
    else:
        logger.debug(
            "Znaleziono tożsamość ID=%s (persona_id=%s)", identity.id, identity.persona_id
        )
    return identity


async def add_identity(
    session: AsyncSession,
    persona: Persona,
    *,
    telegram_user_id: Optional[int] = None,
    telegram_username: Optional[str] = None,
    display_name: Optional[str] = None,
    admin_user_id: Optional[int],
    admin_chat_id: Optional[int],
) -> PersonaIdentity:
    if not any([telegram_user_id, telegram_username, display_name]):
        raise ValueError("Identity must contain at least one identifier")

    sanitized_username = _sanitize_username(telegram_username)
    sanitized_display_name = _sanitize_display_name(display_name)
    normalized_username = _normalise_username(sanitized_username)
    normalized_display_name = _normalise_name(sanitized_display_name)

    existing_stmt = select(PersonaIdentity).where(PersonaIdentity.persona_id == persona.id)
    result = await session.execute(existing_stmt)

    matching: Optional[PersonaIdentity] = None
    for record in result.scalars():
        if telegram_user_id is not None and record.telegram_user_id == telegram_user_id:
            matching = record
            break
        if (
            normalized_username
            and record.telegram_username
            and _normalise_username(record.telegram_username) == normalized_username
        ):
            matching = record
            break
        if (
            normalized_display_name
            and record.display_name
            and _normalise_name(record.display_name) == normalized_display_name
        ):
            matching = record
            break

    now = datetime.now(UTC)

    if matching is None:
        matching = PersonaIdentity(persona_id=persona.id)
        session.add(matching)
        logger.info(
            "Dodaję nową tożsamość dla persony ID=%s (user_id=%s, alias=%s)",
            persona.id,
            telegram_user_id,
            sanitized_username,
        )

    if telegram_user_id is not None:
        matching.telegram_user_id = telegram_user_id
    if sanitized_username is not None:
        matching.telegram_username = sanitized_username
    if sanitized_display_name is not None:
        matching.display_name = sanitized_display_name

    if not any(
        (
            matching.telegram_user_id,
            matching.telegram_username,
            matching.display_name,
        )
    ):
        raise ValueError("Identity must contain at least one identifier")

    matching.added_by_user_id = admin_user_id
    matching.added_in_chat_id = admin_chat_id
    matching.added_at = now

    if matching.removed_at is not None:
        matching.removed_at = None
        matching.removed_by_user_id = None
        matching.removed_in_chat_id = None
        logger.debug("Przywrócono wcześniej usuniętą tożsamość ID=%s", matching.id)

    await session.flush()
    await session.refresh(matching)
    logger.info("Zapisano tożsamość ID=%s dla persony ID=%s", matching.id, persona.id)
    return matching


async def remove_identity(
    session: AsyncSession,
    identity: PersonaIdentity,
    *,
    admin_user_id: Optional[int],
    admin_chat_id: Optional[int],
) -> PersonaIdentity:
    if identity.removed_at is None:
        identity.removed_at = datetime.now(UTC)
        identity.removed_by_user_id = admin_user_id
        identity.removed_in_chat_id = admin_chat_id
        await session.flush()
        await session.refresh(identity)
        logger.info("Oznaczono tożsamość ID=%s jako usuniętą", identity.id)
    return identity


def _sanitize_username(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = value.strip()
    if candidate.startswith("@"):
        candidate = candidate[1:]
    candidate = candidate.strip()
    return candidate or None


def _sanitize_display_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = re.sub(r"\s+", " ", value).strip()
    return candidate or None


def _prepare_identity_query(persona: Persona, include_removed: bool):
    stmt = select(PersonaIdentity).where(PersonaIdentity.persona_id == persona.id)
    if not include_removed:
        stmt = stmt.where(PersonaIdentity.removed_at.is_(None))
    order_clause = case((PersonaIdentity.removed_at.is_(None), 0), else_=1)
    stmt = stmt.order_by(order_clause, PersonaIdentity.id.asc())
    return stmt


async def list_persona_identities(
    session: AsyncSession,
    persona: Persona,
    *,
    include_removed: bool = False,
) -> list[PersonaIdentity]:
    stmt = _prepare_identity_query(persona, include_removed)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_identity_by_id(session: AsyncSession, identity_id: int) -> Optional[PersonaIdentity]:
    result = await session.execute(
        select(PersonaIdentity).where(PersonaIdentity.id == identity_id)
    )
    return result.scalars().first()


async def add_identity(
    session: AsyncSession,
    persona: Persona,
    *,
    telegram_user_id: Optional[int] = None,
    telegram_username: Optional[str] = None,
    display_name: Optional[str] = None,
    admin_user_id: Optional[int],
    admin_chat_id: Optional[int],
) -> PersonaIdentity:
    if not any([telegram_user_id, telegram_username, display_name]):
        raise ValueError("Identity must contain at least one identifier")

    sanitized_username = _sanitize_username(telegram_username)
    sanitized_display_name = _sanitize_display_name(display_name)
    normalized_username = _normalise_username(sanitized_username)
    normalized_display_name = _normalise_name(sanitized_display_name)

    existing_stmt = select(PersonaIdentity).where(PersonaIdentity.persona_id == persona.id)
    result = await session.execute(existing_stmt)

    matching: Optional[PersonaIdentity] = None
    for record in result.scalars():
        if telegram_user_id is not None and record.telegram_user_id == telegram_user_id:
            matching = record
            break
        if (
            normalized_username
            and record.telegram_username
            and _normalise_username(record.telegram_username) == normalized_username
        ):
            matching = record
            break
        if (
            normalized_display_name
            and record.display_name
            and _normalise_name(record.display_name) == normalized_display_name
        ):
            matching = record
            break

    now = datetime.now(UTC)

    if matching is None:
        matching = PersonaIdentity(persona=persona)
        session.add(matching)

    if telegram_user_id is not None:
        matching.telegram_user_id = telegram_user_id
    if sanitized_username is not None:
        matching.telegram_username = sanitized_username
    if sanitized_display_name is not None:
        matching.display_name = sanitized_display_name

    if not any(
        (
            matching.telegram_user_id,
            matching.telegram_username,
            matching.display_name,
        )
    ):
        raise ValueError("Identity must contain at least one identifier")

    matching.added_by_user_id = admin_user_id
    matching.added_in_chat_id = admin_chat_id
    matching.added_at = now

    if matching.removed_at is not None:
        matching.removed_at = None
        matching.removed_by_user_id = None
        matching.removed_in_chat_id = None

    await session.flush()
    await session.refresh(matching)
    return matching


async def remove_identity(
    session: AsyncSession,
    identity: PersonaIdentity,
    *,
    admin_user_id: Optional[int],
    admin_chat_id: Optional[int],
) -> PersonaIdentity:
    if identity.removed_at is None:
        identity.removed_at = datetime.now(UTC)
        identity.removed_by_user_id = admin_user_id
        identity.removed_in_chat_id = admin_chat_id
        await session.flush()
        await session.refresh(identity)
    return identity


__all__ = [
    "IdentityDescriptor",
    "IdentityMatchResult",
    "collect_identity_descriptors",
    "describe_identity",
    "evaluate_submission_identity",
    "list_persona_identities",
    "get_identity_by_id",
    "add_identity",
    "remove_identity",
]
