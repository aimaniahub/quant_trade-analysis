"""
Short-TTL market data cache for Fyers REST payloads.

L1: in-process memory (always)
L2: Redis when available (shared across restarts / multi-worker reads)

Multiple UI polls + strategies hit the same symbols; caching quotes/option
chains for a few seconds collapses duplicate traffic and rate-limit pressure.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class MarketCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._store: Dict[str, Tuple[float, Any]] = {}  # key -> (expires_at, value)
        self.hits = 0
        self.misses = 0
        self.l2_hits = 0
        self.l2_misses = 0
        self.l2_writes = 0

    def _redis_key(self, key: str) -> str:
        from app.services.redis_client import key as rkey
        return rkey("mkt", key)

    def _l2_get(self, key: str) -> Optional[Any]:
        from app.services import redis_client as rc

        if not rc.is_available():
            return None
        try:
            val = rc.get_json(self._redis_key(key))
            if val is None:
                self.l2_misses += 1
                return None
            self.l2_hits += 1
            return val
        except Exception as e:
            logger.debug("[market_cache] l2 get: %s", e)
            self.l2_misses += 1
            return None

    def _l2_set(self, key: str, value: Any, ttl: float) -> None:
        from app.services import redis_client as rc

        if not rc.is_available():
            return
        try:
            # Redis TTL in whole seconds (min 1)
            rc.set_json(self._redis_key(key), value, ttl=max(1, int(ttl)))
            self.l2_writes += 1
        except Exception as e:
            logger.debug("[market_cache] l2 set: %s", e)

    def _l2_clear_pattern(self) -> None:
        """Best-effort clear of market cache keys (SCAN)."""
        from app.services import redis_client as rc

        client = rc.get_redis()
        if not client:
            return
        try:
            prefix = self._redis_key("")
            # prefix ends with trailing piece — use mkt:
            pattern = rc.key("mkt", "*")
            cursor = 0
            while True:
                cursor, keys = client.scan(cursor=cursor, match=pattern, count=200)
                if keys:
                    client.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.debug("[market_cache] l2 clear: %s", e)

    def _purge_expired(self, now: float) -> None:
        dead = [k for k, (exp, _) in self._store.items() if exp <= now]
        for k in dead:
            del self._store[k]

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            item = self._store.get(key)
            if item:
                exp, value = item
                if exp > now:
                    self.hits += 1
                    return value
                del self._store[key]

        # L2 Redis
        l2 = self._l2_get(key)
        if l2 is not None:
            # promote to L1 with remaining short TTL (default 3s if unknown)
            with self._lock:
                self._store[key] = (now + 3.0, l2)
                self.hits += 1
            return l2

        with self._lock:
            self.misses += 1
        return None

    def set(self, key: str, value: Any, ttl: float) -> None:
        now = time.time()
        with self._lock:
            if len(self._store) > 2000:
                self._purge_expired(now)
            self._store[key] = (now + max(ttl, 0.5), value)
        self._l2_set(key, value, ttl)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0
            self.l2_hits = 0
            self.l2_misses = 0
            self.l2_writes = 0
        self._l2_clear_pattern()

    def stats(self) -> Dict[str, Any]:
        from app.services import redis_client as rc

        with self._lock:
            return {
                "entries": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / max(self.hits + self.misses, 1), 3),
                "l2_hits": self.l2_hits,
                "l2_misses": self.l2_misses,
                "l2_writes": self.l2_writes,
                "l2_backend": "redis" if rc.is_available() else "off",
            }

    def cached_call(
        self,
        key: str,
        ttl: float,
        fn: Callable[[], Any],
        cache_errors: bool = False,
    ) -> Any:
        hit = self.get(key)
        if hit is not None:
            if isinstance(hit, dict):
                out = dict(hit)
                out["_cache"] = "hit"
                return out
            return hit

        value = fn()
        ok = True
        if isinstance(value, dict) and value.get("success") is False:
            ok = False
        if ok or cache_errors:
            self.set(key, value, ttl)
        if isinstance(value, dict):
            out = dict(value)
            out["_cache"] = "miss"
            return out
        return value


def make_key(prefix: str, *parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


_cache: Optional[MarketCache] = None


def get_market_cache() -> MarketCache:
    global _cache
    if _cache is None:
        _cache = MarketCache()
    return _cache
