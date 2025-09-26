"""Application configuration and settings management."""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable, List, Optional

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
    def _validate_moderator_chat_id(cls, value: Optional[str]) -> Optional[int]:
        """Convert the moderator chat id to an integer when provided."""

        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ValueError("MODERATOR_CHAT_ID must be an integer") from exc

    @validator("admin_chat_ids", pre=True)
    def _parse_admin_chat_ids(cls, value: Optional[Iterable[int]]) -> List[int]:
        """Normalise the administrator chat identifiers into a list of ints."""

        if value in (None, "", []):
            return []
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",") if item.strip()]
            return [int(item) for item in items]
        return [int(item) for item in value]

    @property
    def moderation_chat_ids(self) -> List[int]:
        """Return the combined list of moderator and admin chat IDs."""

        ids: List[int] = []
        if self.moderator_chat_id is not None:
            ids.append(self.moderator_chat_id)
        ids.extend(self.admin_chat_ids)
        # preserve order while removing duplicates
        seen = set()
        unique_ids: List[int] = []
        for chat_id in ids:
            if chat_id not in seen:
                seen.add(chat_id)
                unique_ids.append(chat_id)
        return unique_ids


@lru_cache()
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
