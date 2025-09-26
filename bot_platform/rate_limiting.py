"""In-memory rate limiting primitives."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Deque, Dict, Tuple


@dataclass(slots=True)
class SlidingWindow:
    limit: int
    interval: timedelta
    timestamps: Deque[datetime]

    def add(self, now: datetime) -> None:
        self.timestamps.append(now)
        self.evict(now)

    def evict(self, now: datetime) -> None:
        threshold = now - self.interval
        while self.timestamps and self.timestamps[0] < threshold:
            self.timestamps.popleft()

    def is_allowed(self, now: datetime) -> bool:
        self.evict(now)
        return len(self.timestamps) < self.limit


class RateLimiter:
    """A simple asynchronous rate limiter with sliding windows."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._windows: Dict[Tuple[str, str], SlidingWindow] = {}

    async def check(self, key: str, bucket: str, *, limit: int, interval_seconds: int) -> bool:
        now = datetime.utcnow()
        interval = timedelta(seconds=interval_seconds)
        window_key = (key, bucket)
        async with self._lock:
            window = self._windows.get(window_key)
            if window is None:
                window = self._windows[window_key] = SlidingWindow(limit, interval, deque())
            window.interval = interval
            if not window.is_allowed(now):
                return False
            window.add(now)
            return True

    async def reset(self, key: str, bucket: str) -> None:
        async with self._lock:
            self._windows.pop((key, bucket), None)


__all__ = ["RateLimiter"]
