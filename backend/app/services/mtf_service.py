"""
Cached Daily / 4H / 1H / 15m history for the MTF engine.

Only called for symbols that already produced option-flow fuel so we
do not burn Fyers quota on the full book every scan.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.mtf_engine import evaluate_mtf
from app.utils.market_hours import IST

logger = logging.getLogger(__name__)

# Resolution → (fyers code, days, ttl seconds)
_SPECS = {
    "D": ("D", 30, 6 * 3600),
    "240": ("240", 45, 3 * 3600),
    "60": ("60", 15, 50 * 60),
    "15": ("15", 6, 90),
}


class MTFService:
    def __init__(self) -> None:
        self._cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}

    def _candles(self, symbol: str, key: str) -> List[Dict[str, Any]]:
        res, days, ttl = _SPECS[key]
        ck = f"{symbol}:{res}"
        now = time.time()
        hit = self._cache.get(ck)
        if hit and hit[0] > now:
            return hit[1]
        try:
            from app.services.fyers_market import get_market_service

            hist = get_market_service().get_historical_data(
                symbol, resolution=res, days=days
            )
            bars = hist.get("candles") or []
        except Exception as exc:
            logger.debug("MTF history %s %s failed: %s", symbol, res, exc)
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
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        daily = daily_candles if daily_candles is not None else self._candles(symbol, "D")
        h4 = self._candles(symbol, "240")
        h1 = self._candles(symbol, "60")
        m15 = m15_candles if m15_candles is not None else self._candles(symbol, "15")
        # If caller passed 5m session bars, still fetch 15m for a real 7/20 stack
        if m15_candles is not None and m15_candles:
            # Prefer dedicated 15m if we have enough bars; else derive nothing — fetch
            fetched = self._candles(symbol, "15")
            if len(fetched) >= 20:
                m15 = fetched
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
