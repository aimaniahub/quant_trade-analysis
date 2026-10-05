"""
Trade lock — scan every harvest, do not re-elect the strike every harvest.

A card stays until invalidation, not until the next snapshot is prettier.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from app.services.chain_anomaly import (
    BIAS_BEAR,
    BIAS_BULL,
    BIAS_CONFLICT,
    GRADE_TRADEABLE,
    GRADE_WATCH,
    _f,
)

STRIKE_WALK_PCT = 8.0
CONFLICT_KILLS = 2


class TradeLockBook:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows: Dict[str, Dict[str, Any]] = {}

    def get(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._rows.get(symbol)
            return dict(row) if row else None

    def clear(self, symbol: Optional[str] = None) -> None:
        with self._lock:
            if symbol:
                self._rows.pop(symbol, None)
            else:
                self._rows.clear()

    def apply(self, report: Dict[str, Any]) -> Dict[str, Any]:
        symbol = report.get("symbol")
        if not symbol:
            return report
        with self._lock:
            locked = self._rows.get(symbol)
            grade = report.get("grade")
            bias = report.get("chain_bias")
            trade = report.get("trade")
            now = time.time()

            if locked:
                locked = dict(locked)
                locked["conflict_streak"] = int(locked.get("conflict_streak") or 0)
                if bias == BIAS_CONFLICT:
                    locked["conflict_streak"] += 1
                else:
                    locked["conflict_streak"] = 0

                kill = None
                if locked["conflict_streak"] >= CONFLICT_KILLS:
                    kill = "Two harvests CONFLICTED"
                elif bias in (BIAS_BULL, BIAS_BEAR) and bias != locked.get("side_bias"):
                    kill = f"Bias flipped to {bias}"
                elif grade not in (GRADE_TRADEABLE, GRADE_WATCH):
                    kill = "Book went quiet"
                else:
                    inv_stop = _f((locked.get("trade") or {}).get("stop"))
                    spot = _f(report.get("spot"))
                    side = locked.get("side_bias")
                    if inv_stop and spot:
                        if side == BIAS_BULL and spot < inv_stop:
                            kill = f"Stop {inv_stop} broken"
                        elif side == BIAS_BEAR and spot > inv_stop:
                            kill = f"Stop {inv_stop} broken"

                if kill:
                    self._rows.pop(symbol, None)
                    report = dict(report)
                    report["lock"] = {
                        "status": "KILLED",
                        "reason": kill,
                        "had": locked.get("trade"),
                    }
                    if report.get("grade") == GRADE_TRADEABLE:
                        report["grade"] = GRADE_WATCH
                    report["trade"] = None
                    report["why_not"] = (
                        (report.get("why_not") + " · " if report.get("why_not") else "")
                        + f"Lock killed: {kill}"
                    )
                    return report

                # Hold the strike unless spot walked 8% off it.
                held = dict(locked.get("trade") or {})
                strike = _f(held.get("strike"))
                spot = _f(report.get("spot"))
                if strike and spot and abs(spot - strike) / spot * 100.0 > STRIKE_WALK_PCT:
                    if trade:
                        held = dict(trade)
                else:
                    # Refresh stop/target from new card if same strike, else keep.
                    if trade and _f(trade.get("strike")) == strike:
                        held = dict(trade)
                    held["locked"] = True
                    held["locked_since"] = locked.get("since")

                locked["trade"] = held
                locked["ts"] = now
                self._rows[symbol] = locked
                report = dict(report)
                report["trade"] = held
                report["grade"] = GRADE_TRADEABLE
                report["lock"] = {"status": "HELD", "since": locked.get("since")}
                report["why_not"] = None
                return report

            if grade == GRADE_TRADEABLE and trade:
                self._rows[symbol] = {
                    "symbol": symbol,
                    "side_bias": bias,
                    "trade": dict(trade),
                    "since": now,
                    "ts": now,
                    "conflict_streak": 0,
                }
                report = dict(report)
                report["lock"] = {"status": "NEW", "since": now}
                return report

            report = dict(report)
            report["lock"] = {"status": "FLAT"}
            return report


_book: Optional[TradeLockBook] = None
_book_lock = threading.Lock()


def get_trade_lock() -> TradeLockBook:
    global _book
    with _book_lock:
        if _book is None:
            _book = TradeLockBook()
        return _book
