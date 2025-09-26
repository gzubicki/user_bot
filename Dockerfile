FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY bot_platform ./bot_platform

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

RUN rm -rf bot_platform

COPY bot_platform ./bot_platform

CMD ["uvicorn", "bot_platform.telegram.webhooks:app", "--host", "0.0.0.0", "--port", "8000"]
