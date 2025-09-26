"""Telegram dispatcher utilities that are aware of moderator chat IDs."""
from __future__ import annotations

from typing import Iterable, Protocol

from bot_platform.config import Settings


class TelegramBotProtocol(Protocol):
    """Simplified protocol representing the interface used by the dispatcher."""

    def send_message(self, chat_id: int, text: str, **kwargs: object) -> None:
        """Send a message to the given chat."""


class ModerationDispatcher:
    """Dispatches Telegram messages to moderators configured in settings."""

    def __init__(self, bot: TelegramBotProtocol, settings: Settings) -> None:
        self._bot = bot
        self._settings = settings

    @property
    def moderation_targets(self) -> Iterable[int]:
        """Return the list of chat IDs used for moderation notifications."""

        return self._settings.moderation_chat_ids

    def notify_moderators(self, text: str, **kwargs: object) -> None:
        """Send a notification message to all moderation chats."""

        for chat_id in self.moderation_targets:
            self._bot.send_message(chat_id=chat_id, text=text, **kwargs)
