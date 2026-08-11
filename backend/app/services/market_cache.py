"""
Short-TTL in-memory cache for Fyers REST payloads.

Multiple UI polls + strategies hit the same symbols; caching quotes/option
chains for a few seconds collapses duplicate traffic and rate-limit pressure.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple


class MarketCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._store: Dict[str, Tuple[float, Any]] = {}  # key -> (expires_at, value)
        self.hits = 0
        self.misses = 0

    def _purge_expired(self, now: float) -> None:
        dead = [k for k, (exp, _) in self._store.items() if exp <= now]
        for k in dead:
            del self._store[k]

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            item = self._store.get(key)
            if not item:
                self.misses += 1
                return None
            exp, value = item
            if exp <= now:
                del self._store[key]
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        now = time.time()
        with self._lock:
            if len(self._store) > 2000:
                self._purge_expired(now)
            self._store[key] = (now + max(ttl, 0.5), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._store),
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / max(self.hits + self.misses, 1), 3),
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
            # Mark response as cache hit when dict
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
