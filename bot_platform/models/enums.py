"""Typy wyliczeniowe wykorzystywane w modelach."""
from __future__ import annotations

import enum


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


__all__ = [
    "MediaType",
    "ModerationStatus",
    "SubscriptionPlan",
]
