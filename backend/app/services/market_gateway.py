"""
Market Gateway — the only Fyers *market-data* door.

Harvest / WS fallback / explicit live=1 use this.
Normal pages read the Symbol Book. Trading (orders/funds) stays on fyers_orders.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STATE_HEALTHY = "HEALTHY"
STATE_WARNING = "WARNING"
STATE_THROTTLED = "THROTTLED"
STATE_COOLDOWN = "COOLDOWN"
STATE_RECOVERING = "RECOVERING"


class MarketGateway:
    def __init__(self):
        self._ws_fallback_quotes_at = 0.0
        self._last_state = STATE_HEALTHY

    def _limiter(self):
        from app.services.rate_limiter import get_fyers_limiter
        return get_fyers_limiter()

    def _market(self):
        from app.services.fyers_market import get_market_service
        return get_market_service()

    def circuit_state(self) -> str:
        lim = self._limiter()
        rpm = lim.requests_last_minute()
        try:
            from app.core.config import get_settings
            cap = int(get_settings().fyers_rpm_limit or 200)
        except Exception:
            cap = 200
        operational = min(180, cap)
        if lim.in_cooldown:
            self._last_state = STATE_COOLDOWN
            return self._last_state
        if rpm >= operational:
            self._last_state = STATE_THROTTLED
            return self._last_state
        if rpm >= int(operational * 0.75):
            self._last_state = STATE_WARNING
            return self._last_state
        if lim.trip_count > 0 and rpm > 0:
            self._last_state = STATE_RECOVERING
            return self._last_state
        self._last_state = STATE_HEALTHY
        return self._last_state

    def stats(self) -> Dict[str, Any]:
        lim = self._limiter()
        st = lim.stats()
        state = self.circuit_state()
        try:
            from app.core.config import get_settings
            cap = int(get_settings().fyers_rpm_limit or 200)
        except Exception:
            cap = 200
        return {
            "state": state,
            "rpm_used": st.get("requests_last_minute", 0),
            "rpm": st.get("requests_last_minute", 0),
            "rpm_limit": cap,
            "limit": cap,
            "429_count": st.get("429_count", 0),
            "cooldown": bool(st.get("cooldown") or lim.in_cooldown),
            "cooldown_remaining": round(lim.cooldown_remaining, 1),
            "rpm_peak": st.get("rpm_peak", 0),
            "min_interval": st.get("min_interval"),
            "total_grants": st.get("total_grants", 0),
        }

    def get_chain(self, symbol: str, strike_count: int = 14, force_refresh: bool = False) -> Dict[str, Any]:
        return self._market().get_option_chain(symbol, strike_count, force_refresh=force_refresh)

    def get_quotes(self, symbols: List[str]) -> Dict[str, Any]:
        return self._market().get_quotes(symbols)

    def get_history(self, symbol: str, resolution: str = "15", days: int = 40, **kw) -> Dict[str, Any]:
        return self._market().get_historical_data(symbol, resolution=resolution, days=days, **kw)

    def rest_quotes_fallback(self, symbols: List[str], *, reason: str = "ws_stale") -> Dict[str, Any]:
        """Batched REST quotes only when the spot stream is down. One loop, not per page."""
        from app.services import symbol_store as store

        now = time.time()
        if self._limiter().in_cooldown:
            logger.info("quotes fallback skipped (cooldown) reason=%s", reason)
            return store.quotes_response_from_spots(list(symbols), store.get_spots(symbols))
        if now - self._ws_fallback_quotes_at < 12:
            logger.debug("quotes fallback skipped (throttled) reason=%s", reason)
            return store.quotes_response_from_spots(list(symbols), store.get_spots(symbols))
        self._ws_fallback_quotes_at = now
        logger.warning("REST quotes fallback reason=%s n=%s", reason, len(symbols))
        with store.harvest_writer():
            return self.get_quotes(symbols)


_gateway: Optional[MarketGateway] = None


def get_market_gateway() -> MarketGateway:
    global _gateway
    if _gateway is None:
        _gateway = MarketGateway()
    return _gateway
