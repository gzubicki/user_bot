"""Ustawienia logowania dla aplikacji i skryptów pomocniczych."""
from __future__ import annotations

import logging
from logging import Logger
from typing import Optional

from pydantic import ValidationError

from .config import get_settings


_CONFIGURED = False


def _resolve_level(level_name: str) -> int:
    """Zwróć numeryczny poziom logowania dla zadanej nazwy."""

    normalized = level_name.strip().upper()
    level = getattr(logging, normalized, None)
    if isinstance(level, int):
        return level
    return logging.INFO


def setup_logging(*, force: bool = False) -> None:
    """Skonfiguruj podstawowe logowanie do konsoli."""

    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    level_name = "INFO"
    error: Exception | None = None
    try:
        settings = get_settings()
    except (ValidationError, RuntimeError, ValueError) as exc:
        error = exc
    else:
        level_name = settings.logging.level

    level = _resolve_level(level_name)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    if error is not None:
        logging.getLogger(__name__).warning(
            "Nie udało się odczytać konfiguracji logowania – używam poziomu %s (%s)",
            level_name,
            error,
        )

    # Wymuszamy bardziej szczegółowe logi dla bibliotek kluczowych dla działania bota.
    for logger_name in ("aiogram", "sqlalchemy.engine"):
        logging.getLogger(logger_name).setLevel(level)

    _CONFIGURED = True


def get_logger(name: Optional[str] = None) -> Logger:
    """Pobierz logger ze wstępną konfiguracją."""

    setup_logging()
    return logging.getLogger(name)


__all__ = ["setup_logging", "get_logger"]
