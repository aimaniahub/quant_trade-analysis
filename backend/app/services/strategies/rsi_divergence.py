"""
Classic RSI divergence on closed bars.

Bull: price lower low + RSI higher low.
Bear: price higher high + RSI lower high.

Pure CPU. No Fyers, no store, no permission.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

PIVOT_LEFT = 4
PIVOT_RIGHT = 2
MIN_PIVOT_GAP = 5
MIN_RSI_GAP = 4.0
BULL_RSI_MAX = 38.0
BEAR_RSI_MIN = 62.0
FRESH_BARS = 3
STALE_BARS = 8
NEAR_VWAP_PCT = 0.5


def _f(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def closed_bars(
    candles: List[Dict[str, Any]],
    period_minutes: int = 15,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    from app.services.mtf_engine import closed_candles

    return closed_candles(candles or [], period_minutes, now=now)


def detect_pivots(
    values: Sequence[Optional[float]],
    *,
    kind: str,
    left: int = PIVOT_LEFT,
    right: int = PIVOT_RIGHT,
) -> List[Tuple[int, float]]:
    """Confirmed fractal pivots. Forming / unconfirmed bars cannot qualify."""
    n = len(values)
    out: List[Tuple[int, float]] = []
    if n < left + right + 1:
        return out
    lo = kind == "low"
    for i in range(left, n - right):
        v = values[i]
        if v is None:
            continue
        left_ok = True
        for x in values[i - left : i]:
            if x is None:
                continue
            if lo and not (v < x):
                left_ok = False
                break
            if not lo and not (v > x):
                left_ok = False
                break
        if not left_ok:
            continue
        right_ok = True
        for x in values[i + 1 : i + 1 + right]:
            if x is None:
                continue
            if lo and v > x:
                right_ok = False
                break
            if not lo and v < x:
                right_ok = False
                break
        if right_ok:
            out.append((i, float(v)))
    return out[-8:]


def _empty(tf: int = 15) -> Dict[str, Any]:
    return {
        "type": None,
        "tf": tf,
        "live": False,
        "fresh": False,
        "stale": False,
        "bars_ago": None,
        "price_l1": None,
        "price_l2": None,
        "rsi_l1": None,
        "rsi_l2": None,
        "bar_l1": None,
        "bar_l2": None,
        "rsi_gap": None,
        "event": None,
        "side": None,
    }


def _pack(
    *,
    kind: str,
    tf: int,
    i1: int,
    i2: int,
    p1: float,
    p2: float,
    r1: float,
    r2: float,
    n: int,
    fresh_bars: int = FRESH_BARS,
    stale_bars: int = STALE_BARS,
) -> Dict[str, Any]:
    bars_ago = n - 1 - i2
    stale = bars_ago > stale_bars
    fresh = (not stale) and bars_ago <= fresh_bars
    live = not stale
    if kind == "BULL_DIV":
        event = "DIV_STALE" if stale else ("BULL_DIV_FRESH" if fresh else "BULL_DIV")
        side = "BULLISH"
        gap = r2 - r1
    else:
        event = "DIV_STALE" if stale else ("BEAR_DIV_FRESH" if fresh else "BEAR_DIV")
        side = "BEARISH"
        gap = r1 - r2
    return {
        "type": kind if live else None,
        "tf": tf,
        "live": live,
        "fresh": fresh,
        "stale": stale,
        "bars_ago": bars_ago,
        "price_l1": round(p1, 4),
        "price_l2": round(p2, 4),
        "rsi_l1": round(r1, 2),
        "rsi_l2": round(r2, 2),
        "bar_l1": i1,
        "bar_l2": i2,
        "rsi_gap": round(gap, 2),
        "event": event,
        "side": side if live else None,
    }


def detect_bullish_divergence(
    price_lows: List[Tuple[int, float]],
    rsi_series: Sequence[Optional[float]],
    *,
    n: int,
    tf: int = 15,
    fresh_bars: int = FRESH_BARS,
    stale_bars: int = STALE_BARS,
) -> Optional[Dict[str, Any]]:
    if len(price_lows) < 2:
        return None
    i1, p1 = price_lows[-2]
    i2, p2 = price_lows[-1]
    if i2 - i1 < MIN_PIVOT_GAP:
        return None
    if p2 >= p1:
        return None
    r1 = rsi_series[i1] if i1 < len(rsi_series) else None
    r2 = rsi_series[i2] if i2 < len(rsi_series) else None
    if r1 is None or r2 is None:
        return None
    if r2 <= r1:
        return None
    if (r2 - r1) < MIN_RSI_GAP:
        return None
    if r2 > BULL_RSI_MAX:
        return None
    return _pack(
        kind="BULL_DIV", tf=tf, i1=i1, i2=i2, p1=p1, p2=p2, r1=r1, r2=r2, n=n,
        fresh_bars=fresh_bars, stale_bars=stale_bars,
    )


def detect_bearish_divergence(
    price_highs: List[Tuple[int, float]],
    rsi_series: Sequence[Optional[float]],
    *,
    n: int,
    tf: int = 15,
    fresh_bars: int = FRESH_BARS,
    stale_bars: int = STALE_BARS,
) -> Optional[Dict[str, Any]]:
    if len(price_highs) < 2:
        return None
    i1, p1 = price_highs[-2]
    i2, p2 = price_highs[-1]
    if i2 - i1 < MIN_PIVOT_GAP:
        return None
    if p2 <= p1:
        return None
    r1 = rsi_series[i1] if i1 < len(rsi_series) else None
    r2 = rsi_series[i2] if i2 < len(rsi_series) else None
    if r1 is None or r2 is None:
        return None
    if r2 >= r1:
        return None
    if (r1 - r2) < MIN_RSI_GAP:
        return None
    if r2 < BEAR_RSI_MIN:
        return None
    return _pack(
        kind="BEAR_DIV", tf=tf, i1=i1, i2=i2, p1=p1, p2=p2, r1=r1, r2=r2, n=n,
        fresh_bars=fresh_bars, stale_bars=stale_bars,
    )


def classify_divergence(
    candles: List[Dict[str, Any]],
    rsi_series: Sequence[Optional[float]],
    *,
    tf: int = 15,
    period_minutes: Optional[int] = None,
    drop_forming: bool = True,
    now: Optional[datetime] = None,
    fresh_bars: int = FRESH_BARS,
    stale_bars: int = STALE_BARS,
) -> Dict[str, Any]:
    """
    Classic divergence on confirmed pivots.
    rsi_series must be aligned with `candles` before drop_forming.
    """
    bars = list(candles or [])
    rsi = list(rsi_series or [])
    if drop_forming:
        period = period_minutes if period_minutes is not None else (
            1440 if tf >= 1440 else 60 if tf == 60 else 15
        )
        closed = closed_bars(bars, period, now=now)
        if len(closed) != len(bars):
            cut = len(bars) - len(closed)
            if cut > 0:
                rsi = rsi[:-cut] if cut < len(rsi) else []
            bars = closed
    n = min(len(bars), len(rsi))
    if n < PIVOT_LEFT + PIVOT_RIGHT + MIN_PIVOT_GAP + 2:
        return _empty(tf)
    bars = bars[:n]
    rsi = rsi[:n]
    lows = [_f(c.get("low")) for c in bars]
    highs = [_f(c.get("high")) for c in bars]
    price_lows = detect_pivots(lows, kind="low")
    price_highs = detect_pivots(highs, kind="high")
    bull = detect_bullish_divergence(
        price_lows, rsi, n=n, tf=tf, fresh_bars=fresh_bars, stale_bars=stale_bars,
    )
    bear = detect_bearish_divergence(
        price_highs, rsi, n=n, tf=tf, fresh_bars=fresh_bars, stale_bars=stale_bars,
    )
    if bull and bear:
        b_ago = int(bull.get("bars_ago") or 99)
        s_ago = int(bear.get("bars_ago") or 99)
        if b_ago < s_ago:
            chosen = bull
        elif s_ago < b_ago:
            chosen = bear
        else:
            return _empty(tf)
        return chosen
    return bull or bear or _empty(tf)


def divergence_score(
    div15: Optional[Dict[str, Any]],
    div60: Optional[Dict[str, Any]] = None,
    *,
    rsi15: Optional[float] = None,
    near_vwap: bool = False,
) -> float:
    d15 = div15 or {}
    if not d15.get("live") or not d15.get("type"):
        return 0.0
    score = 40.0
    d60 = div60 or {}
    if d60.get("live") and d60.get("type") == d15.get("type"):
        score += 25.0
    side = d15.get("side")
    if rsi15 is not None:
        if side == "BULLISH" and rsi15 <= 35:
            score += 15.0
        elif side == "BEARISH" and rsi15 >= 65:
            score += 15.0
    if d15.get("fresh"):
        score += 10.0
    if near_vwap:
        score += 10.0
    return round(min(100.0, score), 1)


def near_session_vwap(spot: float, vwap: Optional[float]) -> bool:
    if not vwap or spot <= 0 or vwap <= 0:
        return False
    return abs(spot - vwap) / vwap * 100.0 <= NEAR_VWAP_PCT


NEAR_MIN_RSI_GAP = 2.5
NEAR_BULL_RSI_MAX = 48.0
NEAR_BEAR_RSI_MIN = 52.0


def _pair_indices(pivots: List[Tuple[int, float]]) -> List[Tuple[int, int]]:
    """Newest-first pivot pairs. Last two first, then skip-one pairs."""
    n = len(pivots)
    out: List[Tuple[int, int]] = []
    if n >= 2:
        out.append((n - 2, n - 1))
    if n >= 3:
        out.append((n - 3, n - 1))
        out.append((n - 3, n - 2))
    if n >= 4:
        out.append((n - 4, n - 1))
    seen = set()
    uniq: List[Tuple[int, int]] = []
    for a, b in out:
        if a == b or (a, b) in seen:
            continue
        seen.add((a, b))
        uniq.append((a, b))
    return uniq


def _geometry(div: Dict[str, Any]) -> Dict[str, Any]:
    p1 = _f(div.get("price_l1"))
    p2 = _f(div.get("price_l2"))
    r1 = _f(div.get("rsi_l1"))
    r2 = _f(div.get("rsi_l2"))
    i1 = div.get("bar_l1")
    i2 = div.get("bar_l2")
    price_pct = ((p2 - p1) / p1 * 100.0) if p1 else 0.0
    rsi_move = r2 - r1
    span = (int(i2) - int(i1)) if i1 is not None and i2 is not None else None
    mag = abs(rsi_move) / max(abs(price_pct), 0.08)
    out = dict(div)
    out["price_move_pct"] = round(price_pct, 3)
    out["rsi_move"] = round(rsi_move, 2)
    out["pivot_span"] = span
    out["div_magnitude"] = round(mag, 2)
    return out


def _bull_pair(
    i1: int,
    p1: float,
    i2: int,
    p2: float,
    rsi: Sequence[Optional[float]],
    *,
    n: int,
    tf: int,
    fresh_bars: int,
    stale_bars: int,
    allow_near: bool,
) -> Optional[Dict[str, Any]]:
    if i2 - i1 < MIN_PIVOT_GAP or p2 >= p1:
        return None
    r1 = rsi[i1] if i1 < len(rsi) else None
    r2 = rsi[i2] if i2 < len(rsi) else None
    if r1 is None or r2 is None or r2 <= r1:
        return None
    gap = r2 - r1
    classic = gap >= MIN_RSI_GAP and r2 <= BULL_RSI_MAX
    if classic:
        pack = _pack(
            kind="BULL_DIV", tf=tf, i1=i1, i2=i2, p1=p1, p2=p2, r1=r1, r2=r2, n=n,
            fresh_bars=fresh_bars, stale_bars=stale_bars,
        )
        pack["near"] = False
        return pack
    if not allow_near:
        return None
    if gap < NEAR_MIN_RSI_GAP or r2 > NEAR_BULL_RSI_MAX:
        return None
    pack = _pack(
        kind="BULL_DIV", tf=tf, i1=i1, i2=i2, p1=p1, p2=p2, r1=r1, r2=r2, n=n,
        fresh_bars=fresh_bars, stale_bars=stale_bars,
    )
    if pack.get("stale") or int(pack.get("bars_ago") or 99) > stale_bars:
        return None
    pack["live"] = False
    pack["type"] = "BULL_DIV"
    pack["side"] = "BULLISH"
    pack["event"] = "NEAR_BULL"
    pack["near"] = True
    pack["near_why"] = "zone" if r2 > BULL_RSI_MAX else "gap"
    pack["stale"] = False
    return pack


def _bear_pair(
    i1: int,
    p1: float,
    i2: int,
    p2: float,
    rsi: Sequence[Optional[float]],
    *,
    n: int,
    tf: int,
    fresh_bars: int,
    stale_bars: int,
    allow_near: bool,
) -> Optional[Dict[str, Any]]:
    if i2 - i1 < MIN_PIVOT_GAP or p2 <= p1:
        return None
    r1 = rsi[i1] if i1 < len(rsi) else None
    r2 = rsi[i2] if i2 < len(rsi) else None
    if r1 is None or r2 is None or r2 >= r1:
        return None
    gap = r1 - r2
    classic = gap >= MIN_RSI_GAP and r2 >= BEAR_RSI_MIN
    if classic:
        pack = _pack(
            kind="BEAR_DIV", tf=tf, i1=i1, i2=i2, p1=p1, p2=p2, r1=r1, r2=r2, n=n,
            fresh_bars=fresh_bars, stale_bars=stale_bars,
        )
        pack["near"] = False
        return pack
    if not allow_near:
        return None
    if gap < NEAR_MIN_RSI_GAP or r2 < NEAR_BEAR_RSI_MIN:
        return None
    pack = _pack(
        kind="BEAR_DIV", tf=tf, i1=i1, i2=i2, p1=p1, p2=p2, r1=r1, r2=r2, n=n,
        fresh_bars=fresh_bars, stale_bars=stale_bars,
    )
    if pack.get("stale") or int(pack.get("bars_ago") or 99) > stale_bars:
        return None
    pack["live"] = False
    pack["type"] = "BEAR_DIV"
    pack["side"] = "BEARISH"
    pack["event"] = "NEAR_BEAR"
    pack["near"] = True
    pack["near_why"] = "zone" if r2 < BEAR_RSI_MIN else "gap"
    pack["stale"] = False
    return pack


def _pick_best(cands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cands:
        return None
    live = [c for c in cands if c.get("live") and not c.get("near")]
    pool = live or cands
    pool.sort(
        key=lambda c: (
            0 if c.get("live") else 1,
            int(c.get("bars_ago") or 99),
            -_f(c.get("rsi_gap")),
        )
    )
    return pool[0]


def analyze_divergence(
    candles: List[Dict[str, Any]],
    rsi_series: Sequence[Optional[float]],
    *,
    tf: int = 15,
    period_minutes: Optional[int] = None,
    drop_forming: bool = True,
    now: Optional[datetime] = None,
    fresh_bars: int = FRESH_BARS,
    stale_bars: int = STALE_BARS,
) -> Dict[str, Any]:
    """Classic live div, extra pivot pairs, then near-miss. Never Fyers."""
    bars = list(candles or [])
    rsi = list(rsi_series or [])
    if drop_forming:
        period = period_minutes if period_minutes is not None else (
            1440 if tf >= 1440 else 60 if tf == 60 else 15
        )
        closed = closed_bars(bars, period, now=now)
        if len(closed) != len(bars):
            cut = len(bars) - len(closed)
            if cut > 0:
                rsi = rsi[:-cut] if cut < len(rsi) else []
            bars = closed
    n = min(len(bars), len(rsi))
    empty = _empty(tf)
    empty["near"] = False
    empty["pivot_lows"] = 0
    empty["pivot_highs"] = 0
    if n < PIVOT_LEFT + PIVOT_RIGHT + MIN_PIVOT_GAP + 2:
        return empty
    bars = bars[:n]
    rsi = rsi[:n]
    lows = [_f(c.get("low")) for c in bars]
    highs = [_f(c.get("high")) for c in bars]
    price_lows = detect_pivots(lows, kind="low")
    price_highs = detect_pivots(highs, kind="high")

    live_cands: List[Dict[str, Any]] = []
    near_cands: List[Dict[str, Any]] = []
    for a, b in _pair_indices(price_lows):
        i1, p1 = price_lows[a]
        i2, p2 = price_lows[b]
        hit = _bull_pair(
            i1, p1, i2, p2, rsi, n=n, tf=tf,
            fresh_bars=fresh_bars, stale_bars=stale_bars, allow_near=False,
        )
        if hit and hit.get("live"):
            live_cands.append(hit)
        else:
            near = _bull_pair(
                i1, p1, i2, p2, rsi, n=n, tf=tf,
                fresh_bars=fresh_bars, stale_bars=stale_bars, allow_near=True,
            )
            if near and near.get("near"):
                near_cands.append(near)
    for a, b in _pair_indices(price_highs):
        i1, p1 = price_highs[a]
        i2, p2 = price_highs[b]
        hit = _bear_pair(
            i1, p1, i2, p2, rsi, n=n, tf=tf,
            fresh_bars=fresh_bars, stale_bars=stale_bars, allow_near=False,
        )
        if hit and hit.get("live"):
            live_cands.append(hit)
        else:
            near = _bear_pair(
                i1, p1, i2, p2, rsi, n=n, tf=tf,
                fresh_bars=fresh_bars, stale_bars=stale_bars, allow_near=True,
            )
            if near and near.get("near"):
                near_cands.append(near)

    chosen = _pick_best(live_cands) or _pick_best(near_cands)
    if not chosen:
        empty["pivot_lows"] = len(price_lows)
        empty["pivot_highs"] = len(price_highs)
        return empty
    chosen = _geometry(chosen)
    chosen["pivot_lows"] = len(price_lows)
    chosen["pivot_highs"] = len(price_highs)
    return chosen


def quality_grade(
    div: Optional[Dict[str, Any]],
    div_htf: Optional[Dict[str, Any]] = None,
    *,
    rsi_now: Optional[float] = None,
    permission: float = 0.0,
    h4_hard: bool = False,
) -> Optional[str]:
    d = div or {}
    if d.get("near"):
        return "C"
    if not d.get("live") or not d.get("type"):
        return None
    if h4_hard:
        return "C"
    htf_ok = bool((div_htf or {}).get("live") and (div_htf or {}).get("type") == d.get("type"))
    extreme = False
    if rsi_now is not None:
        if d.get("side") == "BULLISH" and rsi_now <= 30:
            extreme = True
        if d.get("side") == "BEARISH" and rsi_now >= 70:
            extreme = True
    if d.get("fresh") and extreme and htf_ok and permission >= 60:
        return "A"
    if d.get("fresh") or extreme or htf_ok:
        return "B"
    return "C"
