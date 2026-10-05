"""
Independent 15m / daily history sweeper.

Never runs on the chain critical path. Round-robins stale names with
Radar priority. Yields immediately if a harvest is running or the limiter
is in cooldown.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

SWEEP_IDLE_SECS = 8.0
# Leftover RPM only. Never run at harvest RPS (0.45s ≈ 133 RPM).
SWEEP_TICK_SECS = 2.0


class HistorySweeper:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cursor = 0
        self._nudge: List[str] = []
        self._lock = threading.Lock()
        self._last_cycle_at = 0.0
        self._fills_15 = 0
        self._fills_d = 0
        self._skips = 0
        self._paused = False

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="history-sweeper", daemon=True)
        self._thread.start()
        logger.info("[HistorySweeper] started")

    def stop(self) -> None:
        self._running = False
        self._paused = True

    def pause(self) -> None:
        """Yield the Fyers door to the chain harvest. No REST while paused."""
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def nudge(self, symbols: List[str]) -> None:
        with self._lock:
            head = [s for s in symbols if s]
            self._nudge = list(dict.fromkeys(head + self._nudge))[:400]

    def _ordered_universe(self) -> List[str]:
        from app.services.option_flow_radar import ALL_FNO_WATCHLIST, get_radar_service
        from app.services.fno_stocks import FNO_INDICES, TOP_FNO_STOCKS, filter_valid_symbols
        from app.services.idea_book import get_idea_book

        ordered: List[str] = []
        seen = set()

        def add(syms):
            for s in syms:
                if s and s not in seen:
                    seen.add(s)
                    ordered.append(s)

        with self._lock:
            nudged = list(self._nudge)
            self._nudge = []
        add(nudged)
        try:
            book = get_idea_book().board(limit=25)
            add([i.get("symbol") for i in (book.get("active") or []) + (book.get("confirmed") or [])])
        except Exception:
            pass
        try:
            last = get_radar_service().get_last_scan() or {}
            add([r.get("symbol") for r in (last.get("flagged") or []) if r.get("grade") in ("A+", "A")])
        except Exception:
            pass
        add(filter_valid_symbols(list(FNO_INDICES)))
        add(filter_valid_symbols(list(TOP_FNO_STOCKS)))
        add(list(ALL_FNO_WATCHLIST))
        return ordered

    def _harvest_busy(self) -> bool:
        try:
            from app.services.option_flow_radar import get_radar_service
            return bool(getattr(get_radar_service(), "_scan_running", False))
        except Exception:
            return False

    def _one(self, symbol: str) -> None:
        from app.services import symbol_store as store
        from app.services.rate_limiter import get_fyers_limiter
        from app.services.market_gateway import get_market_gateway

        if self._paused or self._harvest_busy() or get_fyers_limiter().in_cooldown:
            return
        gw = get_market_gateway()
        with store.harvest_writer():
            if not store.is_fresh(symbol, "history.15", store.history_15_ttl()):
                days = store.harvest_history_15_days()
                hist = gw.get_history(symbol, resolution="15", days=days)
                if hist.get("success") and hist.get("candles"):
                    store.put_history(symbol, "15", hist.get("candles") or [], days)
                    self._fills_15 += 1
                else:
                    self._skips += 1
            else:
                self._skips += 1
            if self._paused or self._harvest_busy() or get_fyers_limiter().in_cooldown:
                return
            if not store.is_fresh(symbol, "history.D"):
                days_d = store.harvest_history_d_days()
                daily = gw.get_history(symbol, resolution="D", days=days_d)
                if daily.get("success") and daily.get("candles"):
                    store.put_history(symbol, "D", daily.get("candles") or [], days_d)
                    snap = store.get(symbol) or {}
                    h = ((snap.get("history") or {}).get("D") or {})
                    from datetime import datetime
                    h["ist_date"] = datetime.now().strftime("%Y-%m-%d")
                    store.put(symbol, {"history": {"D": h}})
                    self._fills_d += 1

    def _loop(self) -> None:
        while self._running:
            try:
                if self._paused or self._harvest_busy():
                    time.sleep(2.0)
                    continue
                from app.services.rate_limiter import get_fyers_limiter
                if get_fyers_limiter().in_cooldown:
                    time.sleep(max(get_fyers_limiter().cooldown_remaining, 2.0))
                    continue
                universe = self._ordered_universe()
                if not universe:
                    time.sleep(SWEEP_IDLE_SECS)
                    continue
                n = len(universe)
                # one name per idle tick — leftover RPM after the chain pass
                idx = self._cursor % n
                self._cursor += 1
                self._one(universe[idx])
                self._last_cycle_at = time.time()
                time.sleep(SWEEP_TICK_SECS)
            except Exception as exc:
                logger.debug("[HistorySweeper] %s", exc)
                time.sleep(2.0)

    def status(self) -> dict:
        return {
            "running": self._running,
            "paused": self._paused,
            "fills_15": self._fills_15,
            "fills_d": self._fills_d,
            "skips": self._skips,
            "cursor": self._cursor,
            "last_cycle_at": self._last_cycle_at,
            "tick_secs": SWEEP_TICK_SECS,
        }


_sweeper: Optional[HistorySweeper] = None


def get_history_sweeper() -> HistorySweeper:
    global _sweeper
    if _sweeper is None:
        _sweeper = HistorySweeper()
    return _sweeper
