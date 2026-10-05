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
from collections import deque
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Fyers documented minute cap. Health/telemetry uses this as the budget.
FYERS_RPM_LIMIT = 200
HARVEST_MIN_INTERVAL = 0.33   # ~3.0 RPS, 180 RPM operational cap
IDLE_MIN_INTERVAL = 0.4


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
        self._trip_count = 0
        self._total_grants = 0
        self._grant_times: deque = deque()
        self._wait_tls = threading.local()
        self._rpm_peak = 0

    @property
    def in_cooldown(self) -> bool:
        return time.monotonic() < self._cooldown_until

    @property
    def cooldown_remaining(self) -> float:
        return max(0.0, self._cooldown_until - time.monotonic())

    @property
    def total_grants(self) -> int:
        return self._total_grants

    @property
    def trip_count(self) -> int:
        return self._trip_count

    def set_min_interval(self, interval: float) -> None:
        with self._sync:
            self.min_interval = max(0.05, float(interval))

    def last_wait_s(self) -> float:
        return float(getattr(self._wait_tls, "last_wait", 0.0) or 0.0)

    @property
    def rpm_peak(self) -> int:
        return int(self._rpm_peak)

    def _note_grant_unlocked(self, now: float) -> None:
        self._last_grant = now
        self._total_grants += 1
        self._grant_times.append(now)
        cutoff = now - 60.0
        while self._grant_times and self._grant_times[0] < cutoff:
            self._grant_times.popleft()
        if len(self._grant_times) > self._rpm_peak:
            self._rpm_peak = len(self._grant_times)

    def requests_last_minute(self) -> int:
        now = time.monotonic()
        cutoff = now - 60.0
        with self._sync:
            while self._grant_times and self._grant_times[0] < cutoff:
                self._grant_times.popleft()
            return len(self._grant_times)

    def stats(self) -> Dict[str, Any]:
        rpm = self.requests_last_minute()
        return {
            "requests_last_minute": rpm,
            "limit": FYERS_RPM_LIMIT,
            "cooldown": self.in_cooldown,
            "cooldown_remaining": round(self.cooldown_remaining, 1),
            "429_count": self._trip_count,
            "limit_hits": self._limit_hits,
            "total_grants": self._total_grants,
            "min_interval": self.min_interval,
            "rpm_peak": self._rpm_peak,
        }

    def trip_limit(self, reason: str = "rate limit") -> None:
        """Call when Fyers returns 429 / request limit reached."""
        with self._sync:
            self._limit_hits += 1
            self._trip_count += 1
            extra = min(self.cooldown_on_limit * (1 + self._limit_hits // 3), 180.0)
            self._cooldown_until = time.monotonic() + extra
            hits = self._limit_hits
        logger.warning(
            f"[RateLimiter] {reason} – cooling down {extra:.0f}s "
            f"(hits={hits})"
        )

    def clear_soft(self) -> None:
        """Clear the hit counter after a successful call once cooldown has ended.

        A 1-per-success decrement left 75 leftover hits, so the next 429
        immediately re-armed a 180s cooldown. One clean grant after cooldown
        means the window is open again.
        """
        with self._sync:
            if time.monotonic() >= self._cooldown_until:
                self._limit_hits = 0

    def try_acquire_sync(self) -> Optional[float]:
        """Grant a Fyers token, or None if cooldown is active.

        Does **not** sleep out a 429 cooldown. Harvest workers must skip
        the remaining universe instead of blocking 180s × N.
        Still waits the min_interval between grants.
        """
        waited = 0.0
        while True:
            wait = 0.0
            with self._sync:
                now = time.monotonic()
                if now < self._cooldown_until:
                    self._wait_tls.last_wait = waited
                    return None
                elapsed = now - self._last_grant
                if elapsed < self.min_interval:
                    wait = self.min_interval - elapsed
                else:
                    self._note_grant_unlocked(now)
                    self._wait_tls.last_wait = waited
                    return waited
            if wait > 0:
                time.sleep(wait)
                waited += wait

    def acquire_sync(self) -> float:
        """Block the calling thread until a Fyers token is available. Returns wait seconds."""
        waited = 0.0
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
                        self._note_grant_unlocked(now)
                        self._wait_tls.last_wait = waited
                        return waited
            if wait > 0:
                logger.info("[RateLimiter] waiting %.1fs (sync)", wait)
                time.sleep(wait)
                waited += wait

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

            with self._sync:
                self._note_grant_unlocked(time.monotonic())


_fyers_limiter: Optional[AsyncRateLimiter] = None


def get_fyers_limiter() -> AsyncRateLimiter:
    global _fyers_limiter
    if _fyers_limiter is None:
        # ~2.5–3 req/s keeps well under common 10 RPS caps when other services run
        _fyers_limiter = AsyncRateLimiter(min_interval=0.4, cooldown_on_limit=60.0)
    return _fyers_limiter


def reset_fyers_limiter_for_tests() -> AsyncRateLimiter:
    """Replace the process singleton. Tests only."""
    global _fyers_limiter
    _fyers_limiter = AsyncRateLimiter(min_interval=0.4, cooldown_on_limit=60.0)
    return _fyers_limiter


def is_rate_limit_error(exc_or_msg) -> bool:
    """True only for real Fyers quota / HTTP 429 — not JSON or retry noise."""
    if isinstance(exc_or_msg, dict):
        code = exc_or_msg.get("code")
        nested = exc_or_msg.get("Error") if isinstance(exc_or_msg.get("Error"), dict) else {}
        nested_code = nested.get("code") if nested else None
        if code == 429 or nested_code == 429 or str(code) == "429":
            return True
        text = " ".join(
            str(x)
            for x in (
                code,
                exc_or_msg.get("message"),
                exc_or_msg.get("error"),
                nested.get("message") if nested else None,
                nested.get("error") if nested else None,
            )
            if x is not None
        ).lower()
    else:
        text = str(exc_or_msg).lower()

    if not text:
        return False
    return (
        "429" in text
        or "request limit" in text
        or "rate limit" in text
        or "rate_limit" in text
        or "too many requests" in text
        or "quota exceeded" in text
    )
