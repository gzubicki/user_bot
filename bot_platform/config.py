"""Application configuration and settings management."""
from __future__ import annotations

from collections.abc import Iterable as IterableABC
from functools import lru_cache
from itertools import chain
import re
from typing import Iterable, Iterator, List, Optional, Sequence

from pydantic import BaseSettings, Field, validator


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    telegram_bot_token: str = Field(..., env="TELEGRAM_BOT_TOKEN")
    moderator_chat_id: Optional[int] = Field(None, env="MODERATOR_CHAT_ID")
    admin_chat_ids: List[int] = Field(default_factory=list, env="ADMIN_CHAT_IDS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @validator("moderator_chat_id", pre=True)
    def _validate_moderator_chat_id(cls, value: object) -> Optional[int]:
        """Normalise the moderator chat id to a single integer when provided."""

        chat_ids = cls._parse_chat_id_list(
            value,
            field_name="MODERATOR_CHAT_ID",
            allow_multiple=False,
        )
        return chat_ids[0] if chat_ids else None

    @validator("admin_chat_ids", pre=True)
    def _parse_admin_chat_ids(cls, value: object) -> List[int]:
        """Normalise the administrator chat identifiers into a list of ints."""

        return cls._parse_chat_id_list(
            value,
            field_name="ADMIN_CHAT_IDS",
            allow_multiple=True,
        )

    @property
    def moderation_chat_ids(self) -> Sequence[int]:
        """Return the combined list of moderator and admin chat IDs."""

        combined = chain(
            (self.moderator_chat_id,)
            if self.moderator_chat_id is not None
            else (),
            self.admin_chat_ids,
        )
        return tuple(self._deduplicate(combined))

    @staticmethod
    def _deduplicate(ids: Iterable[int]) -> List[int]:
        """Remove duplicates while preserving the original order."""

        seen = set()
        unique_ids: List[int] = []
        for chat_id in ids:
            if chat_id not in seen:
                seen.add(chat_id)
                unique_ids.append(chat_id)
        return unique_ids

    @classmethod
    def _parse_chat_id_list(
        cls,
        value: object,
        *,
        field_name: str,
        allow_multiple: bool,
    ) -> List[int]:
        """Parse chat identifier data from environment input."""

        items: List[int] = []
        for raw_value in cls._iter_chat_id_values(value):
            try:
                items.append(int(str(raw_value).strip()))
            except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
                raise ValueError(
                    f"{field_name} must contain integer values"
                ) from exc

        if not items:
            return []
        if not allow_multiple and len(items) > 1:
            raise ValueError(
                f"{field_name} must contain exactly one chat identifier"
            )

        return cls._deduplicate(items)

    @staticmethod
    def _iter_chat_id_values(value: object) -> Iterator[object]:
        """Yield raw chat identifier values from diverse environment inputs."""

        if value in (None, "", [], ()):  # support blank env variables
            return iter(())

        if isinstance(value, str):
            segments = re.split(r"[,\s]+", value.strip())
            return (segment for segment in segments if segment)

        if isinstance(value, IterableABC):
            return (item for item in value if item not in (None, ""))

        return iter((value,))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
