"""FastAPI application exposing Telegram webhooks."""
from __future__ import annotations

import asyncio
from typing import Dict

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from aiogram.types import Update
from pydantic import ValidationError

from ..config import get_settings, reload_settings
from ..rate_limiting import RateLimiter
from ..services.bots import (
    ActiveBotToken,
    get_active_bot_tokens,
    get_bot_by_token,
    refresh_bot_token_cache,
)
from .dispatcher import DispatcherBundle, build_dispatcher

app = FastAPI(title="Telegram multi-bot platform")
_rate_limiter = RateLimiter()
_dispatchers: Dict[str, DispatcherBundle] = {}
_dispatcher_lock = asyncio.Lock()


async def _get_dispatcher(bot: ActiveBotToken) -> DispatcherBundle:
    async with _dispatcher_lock:
        bundle = _dispatchers.get(bot.token)
        if bundle is None:
            bundle = build_dispatcher(
                bot.token,
                bot_id=bot.bot_id,
                display_name=bot.display_name,
                persona_id=bot.persona_id,
            )
            _dispatchers[bot.token] = bundle
        return bundle


async def verify_secret(x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if x_telegram_bot_api_secret_token != settings.webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret token")


@app.post("/telegram/{bot_token}")
async def telegram_webhook(
    request: Request,
    bot_token: str,
    _: None = Depends(verify_secret),
) -> JSONResponse:
    bot = await get_bot_by_token(bot_token)
    if bot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown bot token")

    payload = await request.json()
    try:
        update = Update.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid update payload",
        ) from exc
    bundle = await _get_dispatcher(bot)

    chat_id = str(payload.get("message", {}).get("chat", {}).get("id", "global"))
    allowed = await _rate_limiter.check(chat_id, "webhook", limit=5, interval_seconds=1)
    if not allowed:
        return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"status": "rate_limited"})

    await bundle.dispatcher.feed_update(bot=bundle.bot, update=update)
    return JSONResponse(content={"status": "ok"})


@app.post("/internal/reload-config")
async def reload_config(_: None = Depends(verify_secret)) -> JSONResponse:
    reload_settings()
    await refresh_bot_token_cache()
    return JSONResponse(content={"status": "reloaded"})


@app.get("/healthz")
async def healthcheck() -> JSONResponse:
    tokens = await get_active_bot_tokens()
    return JSONResponse(content={"status": "ok", "bots": len(tokens)})
