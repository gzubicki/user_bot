"""Aiogram dispatcher factory."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ..config import get_settings


@dataclass(slots=True)
class DispatcherBundle:
    dispatcher: Dispatcher
    bot: Bot
    moderator_chat_id: int
    bot_id: Optional[int] = None
    display_name: Optional[str] = None


def build_dispatcher(
    token: str,
    *,
    bot_id: Optional[int] = None,
    display_name: Optional[str] = None,
) -> DispatcherBundle:
    """Create a dispatcher bundle for a specific bot token."""

    settings = get_settings()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()

    dispatcher['bot_display_name'] = display_name or token.split(':', 1)[0]
    dispatcher['webhook_secret'] = settings.webhook_secret
    dispatcher['bot_id'] = bot_id
    dispatcher['moderator_chat_id'] = settings.moderation.moderator_chat_id
    return DispatcherBundle(
        dispatcher=dispatcher,
        bot=bot,
        bot_id=bot_id,
        display_name=display_name,
        moderator_chat_id=settings.moderation.moderator_chat_id,
    )


__all__ = ["DispatcherBundle", "build_dispatcher"]
