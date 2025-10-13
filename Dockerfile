FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ALEMBIC_CONFIG=/app/alembic.ini

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY bot_platform ./bot_platform

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

CMD ["uvicorn", "bot_platform.telegram.webhooks:app", "--host", "0.0.0.0", "--port", "8000"]
