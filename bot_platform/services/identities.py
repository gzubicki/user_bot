"""Helpers related to persona identity verification."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..models import Persona, PersonaIdentity, Submission


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


def describe_identity(descriptor: IdentityDescriptor) -> str:
    """Return a human-readable summary of an identity descriptor."""

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
    return tuple(_to_descriptor(identity) for identity in active)


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

    candidate_user_id = getattr(submission, "submitted_by_user_id", None)
    candidate_username = _normalise_username(getattr(submission, "submitted_by_username", None))
    candidate_display_name = _normalise_name(getattr(submission, "submitted_by_name", None))

    descriptors = collect_identity_descriptors(getattr(submission, "persona", None))
    partial_matches: list[tuple[IdentityDescriptor, tuple[str, ...]]] = []

    for descriptor in descriptors:
        matched, matched_fields = _match_descriptor(
            descriptor,
            candidate_user_id=candidate_user_id,
            candidate_username=candidate_username,
            candidate_display_name=candidate_display_name,
        )
        if matched:
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

    return IdentityMatchResult(
        matched=False,
        matched_identity=None,
        matched_fields=tuple(),
        candidate_user_id=candidate_user_id,
        candidate_username=candidate_username,
        candidate_display_name=candidate_display_name,
        descriptors=descriptors,
        partial_matches=tuple(partial_matches),
    )


__all__ = [
    "IdentityDescriptor",
    "IdentityMatchResult",
    "collect_identity_descriptors",
    "describe_identity",
    "evaluate_submission_identity",
]
