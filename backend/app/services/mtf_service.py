"""
Cached Daily / 4H / 1H / 15m history for the MTF engine.

Reads the Redis symbol store. 4H and 1H are derived from stored 15m —
this service must not call Fyers on the reader path.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.mtf_engine import evaluate_mtf
from app.utils.market_hours import IST

logger = logging.getLogger(__name__)

# Resolution → (store code, min_bars, ttl seconds) — ttl is memory only
_SPECS = {
    "D": ("D", 20, 6 * 3600),
    "240": ("240", 20, 3 * 3600),
    "60": ("60", 20, 50 * 60),
    "15": ("15", 20, 90),
}


class MTFService:
    def __init__(self) -> None:
        self._cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}

    def _candles(self, symbol: str, key: str) -> List[Dict[str, Any]]:
        res, min_bars, ttl = _SPECS[key]
        ck = f"{symbol}:{res}"
        now = time.time()
        hit = self._cache.get(ck)
        if hit and hit[0] > now:
            return hit[1]

        from app.services import symbol_store as store

        bars: List[Dict[str, Any]] = []
        if res in ("240", "60"):
            src = store.get_history(symbol, "15", min_bars=20) or []
            if src:
                bars = store.aggregate_ohlcv(src, 240 if res == "240" else 60)
        else:
            bars = store.get_history(symbol, res, min_bars=min_bars) or []

        if not bars:
            logger.debug("MTF store miss %s %s — no Fyers fallback", symbol, res)
            bars = hit[1] if hit else []
        if bars:
            self._cache[ck] = (now + ttl, bars)
        return bars

    def evaluate(
        self,
        symbol: str,
        *,
        daily_candles: Optional[List[Dict[str, Any]]] = None,
        m15_candles: Optional[List[Dict[str, Any]]] = None,
        h4_candles: Optional[List[Dict[str, Any]]] = None,
        h1_candles: Optional[List[Dict[str, Any]]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        daily = daily_candles if daily_candles is not None else self._candles(symbol, "D")
        m15 = m15_candles if m15_candles is not None else self._candles(symbol, "15")
        if h4_candles is not None:
            h4 = h4_candles
        else:
            h4 = self._candles(symbol, "240")
        if h1_candles is not None:
            h1 = h1_candles
        else:
            h1 = self._candles(symbol, "60")
        packed = evaluate_mtf(
            daily_candles=daily or [],
            h4_candles=h4 or [],
            h1_candles=h1 or [],
            m15_candles=m15 or [],
            now=now or datetime.now(IST),
        )
        packed["symbol"] = symbol
        return packed


_svc: Optional[MTFService] = None


def get_mtf_service() -> MTFService:
    global _svc
    if _svc is None:
        _svc = MTFService()
    return _svc
