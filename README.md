# Telegram Multi-Bot Quote Platform

This repository contains the foundations of a multi-bot Telegram platform. Each bot mimics a chosen persona and replies with relevant quotes supplied by the community. All moderation and administration flows happen inside private Telegram chats.

## Key features

- **Multi-bot management** – single backend handles multiple Telegram bots, each with its own persona.
- **Community sourced content** – users forward messages (text, images, audio); administrators moderate each submission.
- **Subscription model** – activation fee (50 Telegram Stars) and recurring per-chat subscription (10 Stars/month), with support for free grants by admins.
- **Configuration hot-reload** – operational limits and pricing stored in environment variables and reloaded without restarting the service.
- **Audit-friendly storage** – Postgres schema keeps track of personas, aliases, submissions, moderation outcomes, subscriptions and audit logs.

## Repository layout

```
bot_platform/
  __init__.py
  config.py
  database.py
  models.py
  rate_limiting.py
  services/
    __init__.py
    moderation.py
    personas.py
    quotes.py
    subscriptions.py
  telegram/
    __init__.py
    dispatcher.py
    webhooks.py
pyproject.toml
README.md
.env.example
```

## Local development

Create a virtual environment (Python 3.11+):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

Copy the configuration template and adjust values:

```bash
cp .env.example .env
```

Run the FastAPI application together with webhook endpoints:

```bash
uvicorn bot_platform.telegram.webhooks:app --reload
```

(For production you would configure Telegram webhooks to hit the `/telegram/{bot_token}` endpoint.)

## Testing

Tests are not included yet. Suggested command:

```bash
pytest
```
