"""Aiogram dispatcher factory."""
from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ..config import get_settings


@dataclass(slots=True)
class DispatcherBundle:
    dispatcher: Dispatcher
    bot: Bot


def build_dispatcher(token: str) -> DispatcherBundle:
    """Create a dispatcher bundle for a specific bot token."""

    settings = get_settings()
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()

    dispatcher['bot_display_name'] = token.split(':', 1)[0]
    dispatcher['webhook_secret'] = settings.webhook_secret
    return DispatcherBundle(dispatcher=dispatcher, bot=bot)


__all__ = ["DispatcherBundle", "build_dispatcher"]
