# User Bot Platform

To configure the Telegram bot, copy `.env.example` to `.env` and adjust the
values for your deployment:

- `TELEGRAM_BOT_TOKEN` – Token issued by [@BotFather](https://t.me/BotFather).
- `MODERATOR_CHAT_ID` – Single numeric chat identifier that should receive
  moderator notifications. Leave unset to disable moderation alerts.
- `ADMIN_CHAT_IDS` – Optional additional chats for escalation messages. The
  value accepts comma- or whitespace-separated identifiers. Non-numeric values
  cause configuration to fail, and duplicates are ignored.

At runtime the application loads these values through
`bot_platform.config.Settings`. The helper exposes `Settings.moderation_chat_ids`
which aggregates the moderator and administrator targets. The Telegram
dispatcher (`bot_platform/telegram/dispatcher.py`) uses this helper to deliver
notifications to every configured moderation chat.
