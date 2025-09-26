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

## Migracje bazy danych

Projekt zawiera wstępnie skonfigurowane środowisko Alembic (`alembic.ini` oraz katalog `alembic/`). Aby zsynchronizować schemat bazy z modelami, ustaw zmienną środowiskową `DATABASE_URL` (np. `export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/dbname`) i uruchom:

```bash
alembic upgrade head
```

Jeśli rozpoczynasz zupełnie nowy projekt i katalog `alembic/` nie istnieje, można go odtworzyć poleceniem `alembic init alembic`. W tym repozytorium nie jest to konieczne – struktura migracji jest gotowa do użycia.

## Running with Docker Compose

Build the application image and start the stack (web app + PostgreSQL):

```bash
cp .env.example .env
docker compose up --build
```

The application service waits for the database service to report a healthy status before booting, so migrations or schema initialization can run safely.

When database migrations are introduced, apply them inside the container (after the services are up) with:

```bash
docker compose run --rm app alembic upgrade head
```

Shut everything down with:

```bash
docker compose down
```

## Testing

Tests are not included yet. Suggested command:

```bash
pytest
```
