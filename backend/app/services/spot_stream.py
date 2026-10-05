"""
Fyers WebSocket → Symbol Book spots.

REST remains for option chain / history. This stream owns LTP/volume for the
canonical F&O universe and reconnects with a full resubscribe.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

WS_FRESH_SECS = 5.0
WS_STALE_SECS = 15.0


def _as_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _tick_src(message: Dict[str, Any]) -> Dict[str, Any]:
    d = message.get("d")
    if isinstance(d, dict):
        return d
    v = message.get("v")
    if isinstance(v, dict):
        return v
    return message


def _normalize_tick(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(message, dict):
        return None
    src = _tick_src(message)
    symbol = (
        message.get("symbol")
        or message.get("n")
        or src.get("symbol")
        or src.get("n")
    )
    if not symbol or not isinstance(symbol, str) or ":" not in symbol:
        return None
    if symbol in ("ok", "error", "success"):
        return None
    ltp = _as_float(src.get("ltp") or src.get("lp") or message.get("ltp") or message.get("lp"))
    if ltp is None or ltp <= 0:
        return None
    chp = _as_float(src.get("chp") or src.get("change_percent") or message.get("chp"))
    ch = _as_float(src.get("ch") or src.get("change") or message.get("ch"))
    vol = _as_float(
        src.get("vol_traded_today")
        or src.get("volume")
        or src.get("vol")
        or message.get("vol_traded_today")
    )
    return {
        "symbol": symbol,
        "ltp": ltp,
        "chg": ch,
        "chg_pct": chp,
        "volume": vol,
        "open": _as_float(src.get("open_price") or src.get("open")),
        "high": _as_float(src.get("high_price") or src.get("high")),
        "low": _as_float(src.get("low_price") or src.get("low")),
        "prev_close": _as_float(src.get("prev_close_price") or src.get("prev_close")),
        "source": "ws",
    }


class SpotStream:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._watch: Optional[threading.Thread] = None
        self._subscribed: List[str] = []
        self._last_tick_at = 0.0
        self._tick_count = 0
        self._reconnects = 0
        self._backoff = 1.0
        self._status = "DISCONNECTED"

    def universe(self) -> List[str]:
        from app.services.option_flow_radar import ALL_FNO_WATCHLIST

        names = list(ALL_FNO_WATCHLIST)
        if "NSE:INDIAVIX-INDEX" not in names:
            names.append("NSE:INDIAVIX-INDEX")
        return names

    def is_connected(self) -> bool:
        from app.services.fyers_websocket import get_websocket_manager
        return bool(get_websocket_manager().data_connected)

    def last_tick_age(self) -> Optional[float]:
        if not self._last_tick_at:
            return None
        return max(0.0, time.time() - self._last_tick_at)

    def is_live(self) -> bool:
        if not self.is_connected():
            return False
        age = self.last_tick_age()
        if age is None:
            return False
        return age <= WS_STALE_SECS

    def on_message(self, message: Any) -> None:
        ticks: List[Dict[str, Any]] = []
        if isinstance(message, list):
            ticks = [m for m in message if isinstance(m, dict)]
        elif isinstance(message, dict):
            d = message.get("d")
            if isinstance(d, list):
                ticks = [m for m in d if isinstance(m, dict)]
            else:
                ticks = [message]
        if not ticks:
            return
        from app.services import symbol_store as store

        now = time.time()
        for raw in ticks:
            spot = _normalize_tick(raw)
            if not spot:
                continue
            store.put_spot(spot["symbol"], spot)
            self._last_tick_at = now
            self._tick_count += 1
            self._backoff = 1.0
            self._status = "CONNECTED"

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return self.is_connected()
            self._running = True
            try:
                self._connect()
            except Exception as exc:
                logger.warning("[SpotStream] initial connect: %s", exc)
            self._watch = threading.Thread(target=self._loop, name="spot-stream", daemon=True)
            self._watch.start()
        return True

    def stop(self) -> None:
        self._running = False

    def _connect(self) -> bool:
        from app.services.fyers_websocket import get_websocket_manager
        from app.services.fyers_auth import get_auth_service

        if not get_auth_service().get_fyers_model():
            self._status = "UNAUTHENTICATED"
            return False
        mgr = get_websocket_manager()
        symbols = self.universe()
        self._subscribed = list(symbols)
        self._status = "CONNECTING"
        subs = mgr._subscribers.get("market_data") or []
        if self.on_message not in subs:
            mgr.add_subscriber("market_data", self.on_message)
        ok = mgr.start_data_stream(symbols, lite_mode=False)
        if ok:
            self._status = "CONNECTED"
            logger.info("[SpotStream] subscribed n=%s", len(symbols))
            return True
        self._status = "DISCONNECTED"
        logger.warning("[SpotStream] connect failed")
        return False

    def _loop(self) -> None:
        while self._running:
            try:
                if self.is_connected():
                    self._status = "CONNECTED"
                    time.sleep(5.0)
                    continue
                self._status = "BACKOFF"
                logger.warning("[SpotStream] disconnected — reconnect in %.0fs", self._backoff)
                time.sleep(self._backoff)
                self._backoff = min(self._backoff * 2.0, 30.0)
                if not self._running:
                    break
                self._status = "RECONNECT"
                self._reconnects += 1
                from app.services.fyers_websocket import get_websocket_manager
                try:
                    get_websocket_manager().stop_all()
                except Exception:
                    pass
                self._connect()
            except Exception as exc:
                logger.warning("[SpotStream] loop: %s", exc)
                time.sleep(3.0)

    def ensure_started(self) -> None:
        if not self._running:
            self.start()
        if not self.is_connected():
            self._connect()

    def status(self) -> Dict[str, Any]:
        age = self.last_tick_age()
        return {
            "status": "connected" if self.is_live() else str(self._status).lower(),
            "connected": self.is_connected(),
            "live": self.is_live(),
            "symbols": len(self._subscribed),
            "subscribed": len(self._subscribed),
            "last_tick_age": round(age, 2) if age is not None else None,
            "tick_count": self._tick_count,
            "reconnects": self._reconnects,
        }


_stream: Optional[SpotStream] = None


def get_spot_stream() -> SpotStream:
    global _stream
    if _stream is None:
        _stream = SpotStream()
    return _stream
