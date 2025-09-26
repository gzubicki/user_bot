"""Zarządzanie konfiguracją aplikacji."""
from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
import re
from typing import Iterator, Tuple

from pydantic import BaseSettings, Field, validator

_CHAT_ID_SEPARATOR = re.compile(r"[,\s]+")


class Settings(BaseSettings):
    """Ładuje konfigurację z otoczenia wykonawczego."""

    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    moderator_chat_id: int | None = Field(default=None, env="MODERATOR_CHAT_ID")
    admin_chat_ids: Tuple[int, ...] = Field(default_factory=tuple, env="ADMIN_CHAT_IDS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @validator("moderator_chat_id", pre=True)
    def _normalise_moderator_chat_id(cls, value: object) -> int | None:
        ids = cls._parse_chat_ids(value, field_name="MODERATOR_CHAT_ID", allow_multiple=False)
        return ids[0] if ids else None

    @validator("admin_chat_ids", pre=True)
    def _normalise_admin_chat_ids(cls, value: object) -> Tuple[int, ...]:
        return cls._parse_chat_ids(value, field_name="ADMIN_CHAT_IDS", allow_multiple=True)

    @property
    def moderation_chat_ids(self) -> Tuple[int, ...]:
        """Zwraca pełną listę czatów do powiadomień moderacyjnych."""

        if self.moderator_chat_id is None:
            return self.admin_chat_ids

        unique: list[int] = [self.moderator_chat_id]
        for chat_id in self.admin_chat_ids:
            if chat_id not in unique:
                unique.append(chat_id)
        return tuple(unique)

    @classmethod
    def _parse_chat_ids(
        cls,
        value: object,
        *,
        field_name: str,
        allow_multiple: bool,
    ) -> Tuple[int, ...]:
        """Przekształca dane wejściowe w krotkę identyfikatorów czatów."""

        tokens = list(cls._iterate_raw_tokens(value))
        if not tokens:
            return ()

        if not allow_multiple and len(tokens) != 1:
            raise ValueError(f"{field_name} musi zawierać dokładnie jeden identyfikator czatu")

        parsed: list[int] = []
        for token in tokens:
            try:
                parsed.append(int(token))
            except ValueError as exc:  # pragma: no cover - walidacja defensywna
                raise ValueError(f"{field_name} musi zawierać wartości liczbowe") from exc

        if allow_multiple:
            return tuple(cls._deduplicate(parsed))
        return tuple(parsed)

    @staticmethod
    def _iterate_raw_tokens(value: object) -> Iterator[str]:
        if value in (None, "", [], ()):  # umożliwiamy pozostawienie pustych zmiennych
            return iter(())

        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return iter(())
            return (segment for segment in _CHAT_ID_SEPARATOR.split(stripped) if segment)

        if isinstance(value, Iterable):
            return (
                stripped
                for item in value
                if (stripped := str(item).strip())
            )

        return iter((str(value).strip(),))

    @staticmethod
    def _deduplicate(values: Iterable[int]) -> Iterable[int]:
        seen: set[int] = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            yield value

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Zwraca singletun z konfiguracją aplikacji."""

    return Settings()
