"""Classic RSI divergence detector + desk hooks."""

from __future__ import annotations

from typing import List, Optional
from unittest.mock import patch

from app.services.strategies.rsi_divergence import (
    BULL_RSI_MAX,
    classify_divergence,
    detect_pivots,
    divergence_score,
)


def _bars(n: int, lows: List[float], highs: List[float]) -> List[dict]:
    out = []
    for i in range(n):
        lo = lows[i]
        hi = highs[i]
        mid = (lo + hi) / 2.0
        out.append({"low": lo, "high": hi, "open": mid, "close": mid, "volume": 1000})
    return out


def _valley_pair(n: int, i1: int, i2: int, p1: float, p2: float, base: float = 100.0):
    lows = [base] * n
    highs = [base + 10] * n
    lows[i1] = p1
    lows[i2] = p2
    return lows, highs


def _peak_pair(n: int, i1: int, i2: int, p1: float, p2: float, base: float = 100.0):
    lows = [base - 10] * n
    highs = [base] * n
    highs[i1] = p1
    highs[i2] = p2
    return lows, highs


def test_bull_div_price_ll_rsi_hl():
    n = 40
    i1, i2 = 31, 37
    lows, highs = _valley_pair(n, i1, i2, 90.0, 85.0)
    rsi: List[Optional[float]] = [50.0] * n
    rsi[i1] = 28.0
    rsi[i2] = 33.0
    ev = classify_divergence(_bars(n, lows, highs), rsi, tf=15, drop_forming=False)
    assert ev["live"] is True
    assert ev["type"] == "BULL_DIV"
    assert ev["fresh"] is True
    assert ev["stale"] is False
    assert ev["bars_ago"] == 2
    assert ev["rsi_gap"] >= 4
    assert ev["rsi_l2"] <= BULL_RSI_MAX


def test_forming_bar_is_not_a_pivot():
    n = 40
    lows, highs = _valley_pair(n, 30, 39, 90.0, 85.0)  # second valley is last bar
    rsi: List[Optional[float]] = [50.0] * n
    rsi[30] = 28.0
    rsi[39] = 33.0
    ev = classify_divergence(_bars(n, lows, highs), rsi, tf=15, drop_forming=False)
    assert ev["live"] is False
    assert ev["type"] is None


def test_pivots_three_bars_apart_rejected():
    n = 40
    lows, highs = _valley_pair(n, 34, 37, 90.0, 85.0)  # gap 3
    rsi: List[Optional[float]] = [50.0] * n
    rsi[34] = 28.0
    rsi[37] = 33.0
    ev = classify_divergence(_bars(n, lows, highs), rsi, tf=15, drop_forming=False)
    assert ev["type"] is None


def test_rsi_gap_two_points_rejected():
    n = 40
    lows, highs = _valley_pair(n, 31, 37, 90.0, 85.0)
    rsi: List[Optional[float]] = [50.0] * n
    rsi[31] = 28.0
    rsi[37] = 30.0
    ev = classify_divergence(_bars(n, lows, highs), rsi, tf=15, drop_forming=False)
    assert ev["type"] is None


def test_second_rsi_low_in_midrange_ignored():
    n = 40
    lows, highs = _valley_pair(n, 31, 37, 90.0, 85.0)
    rsi: List[Optional[float]] = [50.0] * n
    rsi[31] = 28.0
    rsi[37] = 52.0
    ev = classify_divergence(_bars(n, lows, highs), rsi, tf=15, drop_forming=False)
    assert ev["type"] is None
    assert ev["live"] is False


def test_stale_after_eight_bars():
    n = 40
    i1, i2 = 23, 29  # bars_ago = 39-29 = 10
    lows, highs = _valley_pair(n, i1, i2, 90.0, 85.0)
    rsi: List[Optional[float]] = [50.0] * n
    rsi[i1] = 28.0
    rsi[i2] = 33.0
    ev = classify_divergence(_bars(n, lows, highs), rsi, tf=15, drop_forming=False)
    assert ev["stale"] is True
    assert ev["live"] is False
    assert ev["type"] is None
    assert ev["event"] == "DIV_STALE"
    assert divergence_score(ev) == 0.0


def test_bear_div_price_hh_rsi_lh():
    n = 40
    i1, i2 = 31, 37
    lows, highs = _peak_pair(n, i1, i2, 120.0, 130.0)
    rsi: List[Optional[float]] = [50.0] * n
    rsi[i1] = 72.0
    rsi[i2] = 64.0
    ev = classify_divergence(_bars(n, lows, highs), rsi, tf=15, drop_forming=False)
    assert ev["live"] is True
    assert ev["type"] == "BEAR_DIV"
    assert ev["rsi_l2"] == 64.0
    assert ev["fresh"] is True


def test_detect_pivots_needs_right_bars():
    vals = [5, 4, 3, 2, 1, 0]  # last is lowest — not confirmed
    lows = detect_pivots(vals, kind="low", left=2, right=2)
    assert all(i <= len(vals) - 1 - 2 for i, _ in lows)


def test_no_div_score_zero():
    assert divergence_score(_emptyish()) == 0.0


def _emptyish():
    from app.services.strategies.rsi_divergence import classify_divergence

    return classify_divergence([], [], drop_forming=False)


def test_evaluate_4h_short_rejects_bull_div():
    from app.services.strategies.rsi_desk import evaluate_symbol

    n = 40
    i1, i2 = 31, 37
    lows, highs = _valley_pair(n, i1, i2, 90.0, 85.0)
    candles = _bars(n, lows, highs)
    rsi = [50.0] * n
    rsi[i1] = 28.0
    rsi[i2] = 33.0

    with patch("app.services.strategies.rsi_desk.rsi_wilder", return_value=rsi), patch(
        "app.services.strategies.rsi_desk.last_rsi", return_value=33.0
    ), patch(
        "app.services.symbol_store.get_history", return_value=candles
    ), patch(
        "app.services.symbol_store.get", return_value={"spot": {"ltp": 86}}
    ), patch(
        "app.services.symbol_store.aggregate_ohlcv", return_value=candles
    ), patch(
        "app.services.strategies.rsi_desk.mtf_for_symbol",
        return_value={"allowed_side": "SHORT", "h4_bias": "BEARISH"},
    ), patch(
        "app.services.strategies.rsi_desk.mtf_gate",
        return_value={"hard": True, "reason": "MTF_ALLOWED_SIDE", "detail": "4H BEARISH blocks LONG", "allowed_side": "SHORT", "h4_bias": "BEARISH"},
    ), patch(
        "app.services.strategies.rsi_desk.permission_from_snapshot",
        return_value={"p": 70, "hard_fail": [], "hits": [], "miss": [], "liquid": True},
    ):
        ev = evaluate_symbol("NSE:COALINDIA-EQ")
    assert ev.get("success") is True
    assert ev.get("board") == "REJECT"
    assert ev.get("ticket") is None


def test_evaluate_oc_conflict_rejects_bull_div():
    from app.services.strategies.rsi_desk import evaluate_symbol

    n = 40
    i1, i2 = 31, 37
    lows, highs = _valley_pair(n, i1, i2, 90.0, 85.0)
    candles = _bars(n, lows, highs)
    rsi = [50.0] * n
    rsi[i1] = 28.0
    rsi[i2] = 33.0

    with patch("app.services.strategies.rsi_desk.rsi_wilder", return_value=rsi), patch(
        "app.services.strategies.rsi_desk.last_rsi", return_value=33.0
    ), patch(
        "app.services.symbol_store.get_history", return_value=candles
    ), patch(
        "app.services.symbol_store.get", return_value={"spot": {"ltp": 86}}
    ), patch(
        "app.services.symbol_store.aggregate_ohlcv", return_value=candles
    ), patch(
        "app.services.strategies.rsi_desk.mtf_for_symbol",
        return_value={"allowed_side": "LONG", "h4_bias": "BULLISH"},
    ), patch(
        "app.services.strategies.rsi_desk.mtf_gate",
        return_value={"hard": False, "reason": "ALIGNED", "allowed_side": "LONG", "h4_bias": "BULLISH"},
    ), patch(
        "app.services.strategies.rsi_desk.permission_from_snapshot",
        return_value={
            "p": 20,
            "hard_fail": ["OC_CONFLICT"],
            "hits": [],
            "miss": ["knife"],
            "liquid": True,
        },
    ):
        ev = evaluate_symbol("NSE:COALINDIA-EQ")
    assert ev.get("board") == "REJECT"
    assert ev.get("ticket") is None


def test_desk_score_unchanged_without_div():
    from app.services.strategies.rsi_desk import _extreme_score, classify_rsi_event

    ev = classify_rsi_event(40.0, 28.0)
    e = _extreme_score(ev, 32.0, "BULLISH")
    p = 60.0
    desk = round(0.40 * e + 0.60 * p, 1)
    e2 = _extreme_score(ev, 32.0, "BULLISH", div15={"live": False, "type": None})
    assert e2 == e
    from app.services.strategies.rsi_divergence import divergence_score

    assert divergence_score({"live": False}) == 0.0
    assert desk == round(0.40 * e2 + 0.60 * p, 1)


if __name__ == "__main__":
    tests = [
        test_bull_div_price_ll_rsi_hl,
        test_forming_bar_is_not_a_pivot,
        test_pivots_three_bars_apart_rejected,
        test_rsi_gap_two_points_rejected,
        test_second_rsi_low_in_midrange_ignored,
        test_stale_after_eight_bars,
        test_bear_div_price_hh_rsi_lh,
        test_detect_pivots_needs_right_bars,
        test_no_div_score_zero,
        test_desk_score_unchanged_without_div,
        test_evaluate_4h_short_rejects_bull_div,
        test_evaluate_oc_conflict_rejects_bull_div,
    ]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("all ok")
