"""
Redis client for OptionGreek.

Design:
- Optional: if REDIS_ENABLED=false or connection fails → all helpers no-op / return None
- Sync redis-py pool (thread-safe) — matches Fyers sync paths + scan job workers
- JSON helpers with safe defaults
- Key prefixing via settings.redis_prefix

Used for:
- Durable scan jobs
- L2 market data cache (shared across restarts)
- Last radar scan snapshot (confluence)
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_client = None  # redis.Redis | None
_lock = threading.RLock()
_last_error: Optional[str] = None
_last_ping_ok: bool = False
_last_ping_at: float = 0.0
_init_attempted: bool = False


def _settings():
    from app.core.config import get_settings
    return get_settings()


def is_redis_configured() -> bool:
    s = _settings()
    return bool(s.redis_enabled and (s.redis_url or "").strip())


def get_last_error() -> Optional[str]:
    return _last_error


def key(*parts: Any) -> str:
    """Build a namespaced Redis key: {prefix}:a:b:c"""
    prefix = _settings().redis_prefix or "optiongreek"
    segs = [str(prefix)] + [str(p) for p in parts if p is not None and str(p) != ""]
    return ":".join(segs)


def init_redis(force: bool = False) -> bool:
    """
    Initialize Redis connection pool.
    Returns True if connected and PING succeeded.
    """
    global _client, _last_error, _last_ping_ok, _last_ping_at, _init_attempted

    with _lock:
        if _client is not None and not force:
            return _last_ping_ok
        if not is_redis_configured():
            _client = None
            _last_ping_ok = False
            _last_error = None
            _init_attempted = True
            logger.info("[redis] disabled (REDIS_ENABLED=false or empty URL)")
            return False

        _init_attempted = True
        s = _settings()
        try:
            import redis  # type: ignore

            # protocol=2 (RESP2) avoids HELLO which some older Redis / Windows
            # ports reject with "unknown command 'HELLO'".
            common = dict(
                decode_responses=True,
                socket_timeout=s.redis_socket_timeout,
                socket_connect_timeout=s.redis_connect_timeout,
                health_check_interval=30,
                retry_on_timeout=True,
            )
            try:
                _client = redis.Redis.from_url(
                    s.redis_url, protocol=2, **common
                )
            except TypeError:
                # Older redis-py without protocol kwarg
                _client = redis.Redis.from_url(s.redis_url, **common)

            pong = _client.ping()
            _last_ping_ok = bool(pong)
            _last_ping_at = time.time()
            _last_error = None
            logger.info("[redis] connected %s prefix=%s", s.redis_url, s.redis_prefix)
            return True
        except Exception as e:
            _client = None
            _last_ping_ok = False
            _last_error = str(e)
            logger.warning("[redis] unavailable: %s — using in-memory only", e)
            return False


def close_redis() -> None:
    global _client, _last_ping_ok
    with _lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
        _client = None
        _last_ping_ok = False


def get_redis():
    """Return live client or None. Lazily init on first use if configured."""
    global _init_attempted
    if _client is not None:
        return _client
    if not _init_attempted and is_redis_configured():
        init_redis()
    return _client


def ping(force: bool = False) -> bool:
    """Health ping with short cache (5s) unless force."""
    global _last_ping_ok, _last_ping_at, _last_error
    now = time.time()
    if not force and _last_ping_ok and (now - _last_ping_at) < 5:
        return True
    client = get_redis()
    if client is None:
        _last_ping_ok = False
        return False
    try:
        _last_ping_ok = bool(client.ping())
        _last_ping_at = now
        _last_error = None
        return _last_ping_ok
    except Exception as e:
        _last_ping_ok = False
        _last_error = str(e)
        logger.warning("[redis] ping failed: %s", e)
        return False


def is_available() -> bool:
    return ping(force=False)


def status() -> Dict[str, Any]:
    configured = is_redis_configured()
    ok = ping(force=True) if configured else False
    return {
        "enabled": configured,
        "connected": ok,
        "url": _settings().redis_url if configured else None,
        "prefix": _settings().redis_prefix,
        "error": _last_error if configured and not ok else None,
        "backend": "redis" if ok else "memory",
    }


# ── JSON helpers ──────────────────────────────────────────────────

def dumps(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def loads(raw: Optional[str]) -> Any:
    if raw is None or raw == "":
        return None
    return json.loads(raw)


def get_json(k: str) -> Any:
    client = get_redis()
    if not client:
        return None
    try:
        return loads(client.get(k))
    except Exception as e:
        logger.debug("[redis] get_json %s: %s", k, e)
        return None


def set_json(k: str, value: Any, ttl: Optional[int] = None) -> bool:
    client = get_redis()
    if not client:
        return False
    try:
        payload = dumps(value)
        if ttl and ttl > 0:
            client.setex(k, int(ttl), payload)
        else:
            client.set(k, payload)
        return True
    except Exception as e:
        logger.debug("[redis] set_json %s: %s", k, e)
        return False


def delete(*keys: str) -> int:
    client = get_redis()
    if not client or not keys:
        return 0
    try:
        return int(client.delete(*keys))
    except Exception:
        return 0


def expire(k: str, ttl: int) -> bool:
    client = get_redis()
    if not client:
        return False
    try:
        return bool(client.expire(k, int(ttl)))
    except Exception:
        return False


def zadd(k: str, mapping: Dict[str, float]) -> bool:
    client = get_redis()
    if not client:
        return False
    try:
        client.zadd(k, mapping)
        return True
    except Exception as e:
        logger.debug("[redis] zadd %s: %s", k, e)
        return False


def zrevrange(k: str, start: int = 0, end: int = 19) -> List[str]:
    client = get_redis()
    if not client:
        return []
    try:
        return list(client.zrevrange(k, start, end))
    except Exception:
        return []


def zrem(k: str, *members: str) -> int:
    client = get_redis()
    if not client or not members:
        return 0
    try:
        return int(client.zrem(k, *members))
    except Exception:
        return 0
