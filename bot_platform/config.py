"""Configuration helpers for the bot platform."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Dict

_ENV_CACHE: Dict[str, str] = {}


def _load_env_file() -> None:
    """Populate the local cache with values from the nearest .env file."""
    if _ENV_CACHE:
        return

    potential_locations = (
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    )

    for location in potential_locations:
        if not location.exists():
            continue

        for line in location.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue

            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                _ENV_CACHE.setdefault(key, value)
                os.environ.setdefault(key, value)
        break


def _env(name: str, default: str | None = None) -> str | None:
    """Fetch an environment variable, falling back to .env if needed."""
    if name in os.environ:
        return os.environ[name]

    _load_env_file()
    return _ENV_CACHE.get(name, default)


@dataclass(slots=True)
class SubscriptionSettings:
    """Settings dedicated to subscription logic."""

    free_plan_period_days: int

    @classmethod
    def from_env(cls) -> "SubscriptionSettings":
        """Create a settings instance using environment variables."""

        raw_period = _env("SUBSCRIPTION_FREE_PLAN_PERIOD_DAYS", "0")
        try:
            period_days = int(raw_period) if raw_period is not None else 0
        except ValueError as exc:  # pragma: no cover - defensive branch
            raise ValueError(
                "SUBSCRIPTION_FREE_PLAN_PERIOD_DAYS must be an integer"
            ) from exc

        return cls(free_plan_period_days=period_days)


subscription_settings = SubscriptionSettings.from_env()
"""Singleton-style access to subscription configuration."""
