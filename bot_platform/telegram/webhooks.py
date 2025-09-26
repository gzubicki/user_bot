"""FastAPI application exposing Telegram webhooks."""
from __future__ import annotations

import asyncio
from typing import Dict

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from ..config import get_settings, reload_settings
from ..rate_limiting import RateLimiter
from .dispatcher import DispatcherBundle, build_dispatcher

app = FastAPI(title="Telegram multi-bot platform")
_rate_limiter = RateLimiter()
_dispatchers: Dict[str, DispatcherBundle] = {}
_dispatcher_lock = asyncio.Lock()


async def _get_dispatcher(token: str) -> DispatcherBundle:
    async with _dispatcher_lock:
        bundle = _dispatchers.get(token)
        if bundle is None:
            bundle = build_dispatcher(token)
            _dispatchers[token] = bundle
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
    settings = get_settings()
    if bot_token not in settings.bot_tokens:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown bot token")

    payload = await request.json()
    bundle = await _get_dispatcher(bot_token)

    chat_id = str(payload.get("message", {}).get("chat", {}).get("id", "global"))
    allowed = await _rate_limiter.check(chat_id, "webhook", limit=5, interval_seconds=1)
    if not allowed:
        return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"status": "rate_limited"})

    await bundle.dispatcher.feed_update(bot=bundle.bot, update=payload)
    return JSONResponse(content={"status": "ok"})


@app.post("/internal/reload-config")
async def reload_config(_: None = Depends(verify_secret)) -> JSONResponse:
    reload_settings()
    return JSONResponse(content={"status": "reloaded"})


@app.get("/healthz")
async def healthcheck() -> JSONResponse:
    settings = get_settings()
    return JSONResponse(content={"status": "ok", "bots": len(settings.bot_tokens)})
