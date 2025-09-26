# User Bot Platform

This repository contains a small example of a Telegram bot platform. The
application is configured via environment variables and exposes utilities for
sending moderation alerts to pre-defined chats.

## Configuration

Copy the `.env.example` file to `.env` and adjust the variables to match your
Telegram setup. The following variables are currently supported:

- `TELEGRAM_BOT_TOKEN` – Token obtained from [@BotFather](https://t.me/BotFather).
- `MODERATOR_CHAT_ID` – Numeric chat identifier that should receive moderator
  notifications (can point to a group or private chat).
- `ADMIN_CHAT_IDS` – Optional comma-separated list of additional chats that
  should receive escalation messages together with the moderator chat.

When the application starts, `bot_platform.config.Settings` reads these values
and makes them available via convenient helpers, such as
`Settings.moderation_chat_ids`. Telegram integration helpers (see
`bot_platform/telegram/dispatcher.py`) automatically forward moderation alerts
from the dispatcher to all configured chats.
