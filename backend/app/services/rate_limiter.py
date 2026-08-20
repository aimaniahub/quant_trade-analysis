"""
Process-wide async rate limiter for Fyers REST calls.

Fyers free/retail apps often cap around ~10 requests/second and also have
burst / daily limits. This limiter serializes and spaces outbound history/
quote calls so MA + radar + confluence don't stampede the API together.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)


class AsyncRateLimiter:
    def __init__(self, min_interval: float = 0.35, cooldown_on_limit: float = 45.0):
        """
        Args:
            min_interval: minimum seconds between granted tokens (≈3 RPS default)
            cooldown_on_limit: extra sleep after a 429 / "request limit" response
        """
        self.min_interval = min_interval
        self.cooldown_on_limit = cooldown_on_limit
        self._lock = asyncio.Lock()
        self._sync = threading.Lock()
        self._last_grant = 0.0
        self._cooldown_until = 0.0
        self._limit_hits = 0

    @property
    def in_cooldown(self) -> bool:
        return time.monotonic() < self._cooldown_until

    @property
    def cooldown_remaining(self) -> float:
        return max(0.0, self._cooldown_until - time.monotonic())

    def trip_limit(self, reason: str = "rate limit") -> None:
        """Call when Fyers returns 429 / request limit reached."""
        with self._sync:
            self._limit_hits += 1
            extra = min(self.cooldown_on_limit * (1 + self._limit_hits // 3), 180.0)
            self._cooldown_until = time.monotonic() + extra
            hits = self._limit_hits
        logger.warning(
            f"[RateLimiter] {reason} – cooling down {extra:.0f}s "
            f"(hits={hits})"
        )

    def clear_soft(self) -> None:
        """Reset hit counter slowly after a successful stretch."""
        with self._sync:
            if self._limit_hits > 0 and time.monotonic() >= self._cooldown_until:
                self._limit_hits = max(0, self._limit_hits - 1)

    def acquire_sync(self) -> None:
        """Block the calling thread until a Fyers token is available."""
        while True:
            with self._sync:
                now = time.monotonic()
                wait = 0.0
                if now < self._cooldown_until:
                    wait = self._cooldown_until - now
                else:
                    elapsed = now - self._last_grant
                    if elapsed < self.min_interval:
                        wait = self.min_interval - elapsed
                    else:
                        self._last_grant = now
                        return
            if wait > 0:
                logger.info("[RateLimiter] waiting %.1fs (sync)", wait)
                time.sleep(wait)

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # Global cooldown after 429
            if now < self._cooldown_until:
                wait = self._cooldown_until - now
                logger.info(f"[RateLimiter] waiting {wait:.1f}s for cooldown")
                await asyncio.sleep(wait)
                now = time.monotonic()

            elapsed = now - self._last_grant
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)

            self._last_grant = time.monotonic()


_fyers_limiter: Optional[AsyncRateLimiter] = None


def get_fyers_limiter() -> AsyncRateLimiter:
    global _fyers_limiter
    if _fyers_limiter is None:
        # ~2.5–3 req/s keeps well under common 10 RPS caps when other services run
        _fyers_limiter = AsyncRateLimiter(min_interval=0.4, cooldown_on_limit=60.0)
    return _fyers_limiter


def is_rate_limit_error(exc_or_msg) -> bool:
    text = str(exc_or_msg).lower()
    return any(
        tok in text
        for tok in (
            "request limit",
            "rate limit",
            "too many requests",
            "429",
            "quota",
            "throttle",
            "expecting value",
            "max retries exceeded",
        )
    )
