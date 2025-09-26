"""Telegram integration package."""

from .dispatcher import build_dispatcher
from .webhooks import app

__all__ = ["build_dispatcher", "app"]
