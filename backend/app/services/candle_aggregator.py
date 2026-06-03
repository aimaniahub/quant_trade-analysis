"""
Candle Aggregator
=================
Subscribes to raw Fyers tick data (LTP updates) and aggregates them
into 1-minute OHLC candles.  When a candle is closed it fires every
registered callback with the closed candle dict.

Usage (called from MACrossoverService):
    aggregator = CandleAggregator()
    aggregator.register_callback(my_handler)
    aggregator.start()   # launches background thread
    aggregator.stop()
"""

import logging
import threading
import time as _time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

import pytz

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")


class _CandleBuffer:
    """Per-symbol 1-min OHLC accumulator."""

    def __init__(self, symbol: str, minute_ts: int):
        self.symbol = symbol
        self.minute_ts = minute_ts  # unix timestamp floored to minute
        self.open: Optional[float] = None
        self.high: float = float("-inf")
        self.low: float = float("inf")
        self.close: float = 0.0
        self.volume: float = 0.0
        self.tick_count: int = 0

    def update(self, ltp: float, vol: float = 0.0):
        if self.open is None:
            self.open = ltp
        self.high = max(self.high, ltp)
        self.low = min(self.low, ltp)
        self.close = ltp
        self.volume += vol
        self.tick_count += 1

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timestamp": self.minute_ts,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "tick_count": self.tick_count,
        }


class CandleAggregator:
    """
    Aggregates Fyers tick stream into 1-minute OHLC candles and calls
    registered callbacks whenever a candle closes (on the minute boundary).
    """

    def __init__(self):
        self._buffers: Dict[str, _CandleBuffer] = {}
        self._lock = threading.Lock()
        self._callbacks: List[Callable[[Dict], None]] = []
        self._running = False
        self._flush_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_callback(self, fn: Callable[[Dict], None]):
        """Register a function to call with every closed candle dict."""
        self._callbacks.append(fn)

    def on_tick(self, message: Dict):
        """
        Feed a Fyers tick into the aggregator.

        Fyers SymbolUpdate messages contain at minimum:
            {'symbol': 'NSE:SBIN-EQ', 'ltp': 850.5, 'vol_traded_today': 1234567, ...}
        """
        symbol = message.get("symbol") or message.get("s")
        ltp = message.get("ltp") or message.get("v", {}).get("ltp")
        vol = message.get("vol_traded_today") or message.get("v", {}).get("vol_traded_today", 0)

        if not symbol or not ltp:
            return

        now_ts = int(_time.time())
        minute_ts = now_ts - (now_ts % 60)  # floor to minute boundary

        with self._lock:
            buf = self._buffers.get(symbol)
            if buf is None or buf.minute_ts != minute_ts:
                # Close previous candle
                if buf is not None and buf.open is not None:
                    self._fire_callbacks(buf.to_dict())
                # Start new candle
                buf = _CandleBuffer(symbol, minute_ts)
                self._buffers[symbol] = buf
            buf.update(float(ltp), float(vol))

    def start(self):
        """Start the background flush thread that closes stale candles."""
        if self._running:
            return
        self._running = True
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="CandleAggregatorFlusher"
        )
        self._flush_thread.start()
        logger.info("[CandleAggregator] started")

    def stop(self):
        """Stop the aggregator and flush remaining open candles."""
        self._running = False
        with self._lock:
            for buf in list(self._buffers.values()):
                if buf.open is not None:
                    self._fire_callbacks(buf.to_dict())
            self._buffers.clear()
        logger.info("[CandleAggregator] stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fire_callbacks(self, candle: Dict):
        for cb in self._callbacks:
            try:
                cb(candle)
            except Exception as exc:
                logger.error(f"[CandleAggregator] callback error: {exc}")

    def _flush_loop(self):
        """
        Every 5 seconds, check if any buffer is more than 90 seconds old
        (i.e. the candle minute has passed) and close it.  This handles
        symbols that stop receiving ticks mid-session.
        """
        while self._running:
            _time.sleep(5)
            now_ts = int(_time.time())
            minute_ts = now_ts - (now_ts % 60)

            with self._lock:
                stale = [
                    sym
                    for sym, buf in self._buffers.items()
                    if buf.minute_ts < minute_ts and buf.open is not None
                ]
                for sym in stale:
                    buf = self._buffers.pop(sym)
                    self._fire_callbacks(buf.to_dict())


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_aggregator: Optional[CandleAggregator] = None


def get_candle_aggregator() -> CandleAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = CandleAggregator()
    return _aggregator
