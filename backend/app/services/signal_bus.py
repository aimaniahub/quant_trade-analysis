"""
In-memory strategy signal bus.

Collects signals from MA, intelligence, radar, VAT etc. and:
  • keeps a short ring buffer for REST polling
  • fans out to registered async broadcasters (e.g. /ws/alerts)
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional

import pytz

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

BroadcastFn = Callable[[Dict[str, Any]], Awaitable[None]]


class SignalBus:
    def __init__(self, max_events: int = 100, dedupe_seconds: float = 120.0):
        self._events: Deque[Dict[str, Any]] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._broadcasters: List[BroadcastFn] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._dedupe_seconds = dedupe_seconds
        self._recent_keys: Dict[str, float] = {}
        self._seq = 0

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def register_broadcaster(self, fn: BroadcastFn) -> None:
        if fn not in self._broadcasters:
            self._broadcasters.append(fn)

    def unregister_broadcaster(self, fn: BroadcastFn) -> None:
        if fn in self._broadcasters:
            self._broadcasters.remove(fn)

    def publish(
        self,
        source: str,
        message: str,
        *,
        level: str = "signal",
        symbol: Optional[str] = None,
        score: Optional[float] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        # Dedupe identical source+symbol+message within window (stops 30s poll spam)
        dedupe_key = f"{source}|{symbol or ''}|{message}"
        now = time.time()
        with self._lock:
            last = self._recent_keys.get(dedupe_key, 0)
            if now - last < self._dedupe_seconds:
                return None
            self._recent_keys[dedupe_key] = now
            # Opportunistic cleanup
            if len(self._recent_keys) > 500:
                cutoff = now - self._dedupe_seconds
                self._recent_keys = {
                    k: v for k, v in self._recent_keys.items() if v >= cutoff
                }

        with self._lock:
            self._seq += 1
            seq = self._seq
        # Unique even when multiple events fire in the same millisecond
        event_id = f"{int(now * 1000)}-{source}-{seq}-{uuid.uuid4().hex[:6]}"

        event = {
            "id": event_id,
            "source": source,
            "type": level,  # signal | warning | info
            "message": message,
            "symbol": symbol,
            "score": score,
            "meta": meta or {},
            "timestamp": datetime.now(IST).isoformat(),
            "ts": now,
        }
        with self._lock:
            self._events.appendleft(event)

        self._fanout(event)
        return event

    def recent(self, limit: int = 20, source: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._events)
        if source:
            items = [e for e in items if e.get("source") == source]
        return items[: max(1, min(limit, 100))]

    def _fanout(self, event: Dict[str, Any]) -> None:
        if not self._broadcasters:
            return
        loop = self._loop
        try:
            if loop is None:
                loop = asyncio.get_running_loop()
                self._loop = loop
        except RuntimeError:
            loop = self._loop

        for fn in list(self._broadcasters):
            try:
                if loop and loop.is_running():
                    asyncio.run_coroutine_threadsafe(fn(event), loop)
                else:
                    # Best-effort when called from async context without bound loop
                    try:
                        running = asyncio.get_running_loop()
                        running.create_task(fn(event))
                    except RuntimeError:
                        pass
            except Exception as exc:
                logger.debug(f"Signal bus fanout error: {exc}")


_bus: Optional[SignalBus] = None


def get_signal_bus() -> SignalBus:
    global _bus
    if _bus is None:
        _bus = SignalBus()
    return _bus
