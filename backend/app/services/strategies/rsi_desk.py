"""
RSI desk: 15m + derived 1H extremes × option-chain permission.

Same harvest book as 7/200. No Fyers. No universe 5m.
TRADE = stretched RSI + reclaim (or P>=75) + OC agrees + 4H allows.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.fno_stocks import FNO_STOCKS, filter_valid_symbols
from app.services.strategies.ma7200_desk import (
    P_A,
    P_AVOID,
    P_SETUP,
    T_SETUP,
    _ema,
    _f,
    build_ticket,
    compute_adx,
    compute_atr,
    mtf_for_symbol,
    mtf_gate,
    permission_from_snapshot,
    session_vwap,
)
from app.services.strategies.rsi_divergence import (
    BEAR_RSI_MIN,
    BULL_RSI_MAX,
    classify_divergence,
    divergence_score,
    near_session_vwap,
)

RSI_PERIOD = 14
RSI_OB = 70.0
RSI_OS = 30.0
RSI_HTF_OS_SOFT = 45.0
RSI_HTF_OB_SOFT = 55.0
RECLAIM_OR_STUCK_P = 75.0
REL_VOL_SOFT = 0.8


def rsi_wilder(candles: List[Dict[str, Any]], period: int = RSI_PERIOD) -> List[Optional[float]]:
    """Wilder RSI series aligned with candles. None until seeded."""
    n = len(candles)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    closes = [_f(c.get("close")) for c in candles]
    gains: List[float] = [0.0]
    losses: List[float] = [0.0]
    for i in range(1, n):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    avg_g = sum(gains[1 : period + 1]) / period
    avg_l = sum(losses[1 : period + 1]) / period
    if avg_l <= 1e-12:
        out[period] = 100.0
    else:
        out[period] = 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    for i in range(period + 1, n):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        if avg_l <= 1e-12:
            out[i] = 100.0
        else:
            out[i] = 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    return out


def last_rsi(series: List[Optional[float]]) -> Optional[float]:
    for v in reversed(series):
        if v is not None:
            return round(float(v), 2)
    return None


def classify_rsi_event(
    prev: Optional[float],
    now: Optional[float],
    *,
    lo: float = RSI_OS,
    hi: float = RSI_OB,
) -> Dict[str, Any]:
    """
    enter_os / enter_ob / reclaim_os (back above 30) / reclaim_ob (back below 70)
    / stuck_os / stuck_ob / none
    """
    if now is None:
        return {"event": "NONE", "zone": None, "fresh": False, "reclaim": False}
    zone = "OS" if now <= lo else "OB" if now >= hi else "MID"
    prev_z = None
    if prev is not None:
        prev_z = "OS" if prev <= lo else "OB" if prev >= hi else "MID"

    event = "NONE"
    reclaim = False
    fresh = False
    if zone == "OS" and prev_z != "OS":
        event, fresh = "ENTER_OS", True
    elif zone == "OB" and prev_z != "OB":
        event, fresh = "ENTER_OB", True
    elif zone != "OS" and prev_z == "OS":
        event, reclaim, fresh = "RECLAIM_OS", True, True
    elif zone != "OB" and prev_z == "OB":
        event, reclaim, fresh = "RECLAIM_OB", True, True
    elif zone == "OS":
        event = "STUCK_OS"
    elif zone == "OB":
        event = "STUCK_OB"
    return {
        "event": event,
        "zone": zone,
        "fresh": fresh,
        "reclaim": reclaim,
        "rsi": now,
        "rsi_prev": prev,
    }


def _rel_vol(candles: List[Dict], lookback: int = 20) -> Optional[float]:
    if len(candles) < 4:
        return None
    vols = [_f(c.get("volume")) for c in candles]
    cur = vols[-1]
    prev = vols[-lookback - 1 : -1] if len(vols) > lookback else vols[:-1]
    if not prev:
        return None
    avg = sum(prev) / len(prev)
    if avg <= 0:
        return None
    return round(cur / avg, 2)


def _ema20_side(candles: List[Dict], spot: float) -> Optional[str]:
    closes = [_f(c.get("close")) for c in candles]
    series = _ema(closes, 20)
    last = next((v for v in reversed(series) if v is not None), None)
    if last is None or spot <= 0:
        return None
    return "ABOVE" if spot >= last else "BELOW"


def _div_agrees(div: Optional[Dict[str, Any]], side: str) -> bool:
    d = div or {}
    if not d.get("live"):
        return False
    t = d.get("type")
    if side == "BULLISH" and t == "BULL_DIV":
        return True
    if side == "BEARISH" and t == "BEAR_DIV":
        return True
    return False


def _extreme_score(
    ev15: Dict[str, Any],
    rsi60: Optional[float],
    side: str,
    div15: Optional[Dict[str, Any]] = None,
    div60: Optional[Dict[str, Any]] = None,
) -> float:
    e = 0.0
    r15 = ev15.get("rsi")
    if r15 is None:
        return 0.0
    scored_zone = False
    if side == "BULLISH" and ev15.get("zone") == "OS":
        e += 35
        scored_zone = True
    elif side == "BEARISH" and ev15.get("zone") == "OB":
        e += 35
        scored_zone = True
    elif ev15.get("reclaim") and side == "BULLISH" and ev15.get("event") == "RECLAIM_OS":
        e += 35
        scored_zone = True
    elif ev15.get("reclaim") and side == "BEARISH" and ev15.get("event") == "RECLAIM_OB":
        e += 35
        scored_zone = True

    if scored_zone and rsi60 is not None:
        if side == "BULLISH":
            if rsi60 <= RSI_OS:
                e += 25
            elif rsi60 <= RSI_HTF_OS_SOFT:
                e += 10
            elif rsi60 >= RSI_HTF_OB_SOFT:
                e -= 15
        else:
            if rsi60 >= RSI_OB:
                e += 25
            elif rsi60 >= RSI_HTF_OB_SOFT:
                e += 10
            elif rsi60 <= RSI_HTF_OS_SOFT:
                e -= 15

        if ev15.get("reclaim"):
            e += 15
        elif ev15.get("fresh"):
            e += 8
        depth = (RSI_OS - r15) if side == "BULLISH" else (r15 - RSI_OB)
        e += min(10.0, max(0.0, depth))

    if _div_agrees(div15, side):
        e += 15
        if _div_agrees(div60, side):
            e += 10
        if (side == "BULLISH" and r15 <= 35) or (side == "BEARISH" and r15 >= 65):
            e += 5

    if not scored_zone and e <= 0:
        return 0.0
    return round(max(0.0, min(100.0, e)), 1)


def _classify_board(
    *,
    side: str,
    ev15: Dict[str, Any],
    e_score: float,
    perm: Dict[str, Any],
    gate: Dict[str, Any],
    rel_vol: Optional[float],
    div15: Optional[Dict[str, Any]] = None,
) -> tuple:
    p = float(perm.get("p") or 0)
    hard = list(perm.get("hard_fail") or [])
    reclaim = bool(ev15.get("reclaim"))
    zone = ev15.get("zone")
    r15 = ev15.get("rsi")
    live_div = _div_agrees(div15, side)
    near_band = (
        (side == "BULLISH" and r15 is not None and float(r15) <= BULL_RSI_MAX)
        or (side == "BEARISH" and r15 is not None and float(r15) >= BEAR_RSI_MIN)
    )

    if gate.get("hard"):
        return "REJECT", gate.get("detail") or gate.get("reason") or "MTF hard gate"
    if "OC_CONFLICT" in hard or "FUTURES_OPPOSITE" in hard:
        return "REJECT", "; ".join(perm.get("miss") or hard) or "OC / futures conflict"
    if "NO_CHAIN" in hard:
        return "WATCH", "No stored chain yet"

    # Sponsored overbought is momentum, not a fade
    if side == "BEARISH" and (zone == "OB" or live_div):
        bias = ((perm.get("buildup") or {}).get("bias") or "").upper()
        if bias == "BULLISH" and "OC_CONFLICT" not in hard:
            return "WATCH", "Overbought + bullish chain — strength, do not fade"

    if zone == "MID" and not reclaim:
        if live_div and near_band:
            pass
        else:
            return "REJECT", "RSI not extreme"

    if p < P_AVOID:
        return "REJECT", f"Permission {p:.0f} < {P_AVOID:.0f}"

    if "NO_VEHICLE" in hard:
        return "WATCH", "Thin ATM options"

    if gate.get("soft"):
        return "WATCH", "4H mixed — no ticket"

    if rel_vol is not None and rel_vol < REL_VOL_SOFT:
        return "WATCH", f"Rel vol {rel_vol:.2f}× < {REL_VOL_SOFT} — weak participation"

    ticket_ok = (reclaim and p >= P_SETUP and e_score >= T_SETUP) or (
        not reclaim and p >= RECLAIM_OR_STUCK_P and e_score >= T_SETUP
    )
    if ticket_ok:
        grade = "A-SETUP" if (reclaim and p >= P_A and e_score >= 70) else "SETUP"
        return "TRADE", grade
    if live_div and not reclaim:
        return "WATCH", "divergence, wait reclaim"
    if reclaim:
        return "WATCH", f"Reclaim but P {p:.0f} / E {e_score:.0f} not ticket-ready"
    return "WATCH", f"Stuck extreme — wait reclaim (or P≥{RECLAIM_OR_STUCK_P:.0f})"


def _name(symbol: str) -> str:
    return symbol.replace("NSE:", "").replace("-EQ", "").replace("-INDEX", "")


def evaluate_symbol(symbol: str) -> Dict[str, Any]:
    """One name from the harvest book."""
    from app.services import symbol_store as store

    m15 = store.get_history(symbol, "15", min_bars=RSI_PERIOD + 5) or []
    if len(m15) < RSI_PERIOD + 5:
        return {
            "success": False,
            "error": "15m book not harvested yet",
            "symbol": symbol,
        }

    h1 = store.get_history(symbol, "60", min_bars=RSI_PERIOD + 5) or []
    if len(h1) < RSI_PERIOD + 5:
        h1 = store.aggregate_ohlcv(m15, 60)

    r15s = rsi_wilder(m15)
    r60s = rsi_wilder(h1) if h1 else []
    rsi15 = last_rsi(r15s)
    rsi60 = last_rsi(r60s)
    prev15 = None
    for v in reversed(r15s[:-1]):
        if v is not None:
            prev15 = round(float(v), 2)
            break
    ev15 = classify_rsi_event(prev15, rsi15)
    div15 = classify_divergence(m15, r15s, tf=15)
    div60 = classify_divergence(h1, r60s, tf=60, period_minutes=60) if h1 else {}

    # Intended trade side from the 15m zone / reclaim / live divergence band
    if ev15["event"] in ("ENTER_OS", "STUCK_OS", "RECLAIM_OS") or ev15.get("zone") == "OS":
        side = "BULLISH"
    elif ev15["event"] in ("ENTER_OB", "STUCK_OB", "RECLAIM_OB") or ev15.get("zone") == "OB":
        side = "BEARISH"
    elif (
        div15.get("live")
        and div15.get("type") == "BULL_DIV"
        and rsi15 is not None
        and rsi15 <= BULL_RSI_MAX
    ):
        side = "BULLISH"
    elif (
        div15.get("live")
        and div15.get("type") == "BEAR_DIV"
        and rsi15 is not None
        and rsi15 >= BEAR_RSI_MIN
    ):
        side = "BEARISH"
    else:
        return {
            "success": True,
            "symbol": symbol,
            "name": _name(symbol),
            "board": "REJECT",
            "board_reason": "RSI 15m not extreme",
            "rsi15": rsi15,
            "rsi60": rsi60,
            "event": ev15["event"],
            "zone": ev15.get("zone"),
            "div_live": False,
            "div_type": None,
        }

    snap = store.get(symbol) or {}
    spot = _f((snap.get("spot") or {}).get("ltp") or m15[-1].get("close"))
    mtf = mtf_for_symbol(symbol)
    gate = mtf_gate(side, mtf)
    perm = permission_from_snapshot(symbol, side, snap=snap, spot=spot)
    e_score = _extreme_score(ev15, rsi60, side, div15=div15, div60=div60)
    rel_vol = _rel_vol(m15)
    vwap = session_vwap(m15)
    adx = compute_adx(m15)
    atr = compute_atr(m15)
    ema20 = _ema20_side(m15, spot)

    board, reason = _classify_board(
        side=side,
        ev15=ev15,
        e_score=e_score,
        perm=perm,
        gate=gate,
        rel_vol=rel_vol,
        div15=div15,
    )

    ticket = None
    grade = None
    if board == "TRADE" and not gate.get("hard"):
        fake_cross = {
            "ema200": None,
            "ltp": spot,
            "volume_ratio": rel_vol,
            "bars_ago": 0 if ev15.get("fresh") or ev15.get("reclaim") else 2,
            "fresh_label": ev15.get("event"),
        }
        # stop uses 200 if present — fall back to EMA20 from 15m
        closes = [_f(c.get("close")) for c in m15]
        e20 = next((v for v in reversed(_ema(closes, 20)) if v is not None), None)
        fake_cross["ema200"] = e20
        ticket = build_ticket(
            symbol=symbol,
            cross_type=side,
            cross=fake_cross,
            perm=perm,
            mtf=mtf,
            adx=adx,
            vwap=vwap,
            atr=atr,
        )
        if not ticket:
            board, reason = "WATCH", "Permission ok but no vehicle"
        else:
            bits = [
                f"RSI15 {rsi15} {ev15['event']}",
                f"RSI60 {rsi60}",
                "reclaim" if ev15.get("reclaim") else "extreme",
            ]
            if div15.get("live") and div15.get("event"):
                bits.append(str(div15.get("event")))
            ticket["trigger"] = " · ".join(str(b) for b in bits if b)
            grade = reason if reason in ("A-SETUP", "SETUP") else "SETUP"

    if gate.get("hard"):
        board = "REJECT"
        ticket = None
        grade = None

    d_score = divergence_score(
        div15,
        div60,
        rsi15=rsi15,
        near_vwap=near_session_vwap(spot, vwap),
    )
    if div15.get("live") and _div_agrees(div15, side):
        desk_score = round(0.35 * e_score + 0.25 * d_score + 0.40 * float(perm.get("p") or 0), 1)
    else:
        desk_score = round(0.40 * e_score + 0.60 * float(perm.get("p") or 0), 1)
    hits = perm.get("hits") or []

    return {
        "success": True,
        "symbol": symbol,
        "name": _name(symbol),
        "ltp": spot,
        "side": side,
        "thesis": "BOUNCE" if side == "BULLISH" else "FADE",
        "rsi15": rsi15,
        "rsi60": rsi60,
        "rsi5": None,
        "event": ev15.get("event"),
        "zone": ev15.get("zone"),
        "reclaim": bool(ev15.get("reclaim")),
        "fresh": bool(ev15.get("fresh")),
        "extreme_score": e_score,
        "permission": perm.get("p"),
        "permission_hits": hits,
        "permission_miss": perm.get("miss") or [],
        "hard_fail": perm.get("hard_fail") or [],
        "buildup_state": (perm.get("buildup") or {}).get("primary_state"),
        "buildup_note": (perm.get("buildup") or {}).get("note"),
        "futures_state": (perm.get("futures") or {}).get("state"),
        "oi_pcr": perm.get("oi_pcr"),
        "atm_iv": perm.get("atm_iv"),
        "put_wall": (perm.get("walls") or {}).get("put_wall"),
        "call_wall": (perm.get("walls") or {}).get("call_wall"),
        "rel_vol": rel_vol,
        "vwap": round(vwap, 2) if vwap else None,
        "ema20": ema20,
        "adx": adx,
        "h4_bias": gate.get("h4_bias") or mtf.get("h4_bias"),
        "mtf_allowed": gate.get("allowed_side"),
        "mtf_gate": gate.get("reason"),
        "mtf_gate_hard": bool(gate.get("hard")),
        "desk_score": desk_score,
        "board": board,
        "board_reason": reason,
        "grade": grade,
        "ticket": ticket,
        "htf_priority": (
            "A"
            if rsi60 is not None
            and (
                (side == "BULLISH" and rsi15 is not None and rsi15 <= RSI_OS and rsi60 <= RSI_OS)
                or (side == "BEARISH" and rsi15 is not None and rsi15 >= RSI_OB and rsi60 >= RSI_OB)
            )
            else "B"
            if rsi60 is not None
            and (
                (side == "BULLISH" and rsi60 <= RSI_HTF_OS_SOFT)
                or (side == "BEARISH" and rsi60 >= RSI_HTF_OB_SOFT)
            )
            else "C"
        ),
        "div_type": div15.get("type") if div15.get("live") else None,
        "div_event": div15.get("event") if div15.get("live") else None,
        "div_live": bool(div15.get("live")),
        "div_fresh": bool(div15.get("fresh")),
        "div_stale": bool(div15.get("stale")),
        "div_bars_ago": div15.get("bars_ago"),
        "div_rsi_gap": div15.get("rsi_gap"),
        "div_price_l1": div15.get("price_l1"),
        "div_price_l2": div15.get("price_l2"),
        "div_rsi_l1": div15.get("rsi_l1"),
        "div_rsi_l2": div15.get("rsi_l2"),
        "div60_type": div60.get("type") if (div60 or {}).get("live") else None,
        "div_score": d_score,
    }


def scan_book(*, source: str = "full", limit: int = 200) -> Dict[str, Any]:
    """CPU scan of harvested F&O equities. No Fyers."""
    from app.services import symbol_store as store
    from app.services.fno_stocks import TOP_FNO_STOCKS

    if source == "top":
        symbols = filter_valid_symbols(list(TOP_FNO_STOCKS))[:limit]
    else:
        symbols = filter_valid_symbols(list(FNO_STOCKS))[:limit]

    trade: List[Dict[str, Any]] = []
    watch: List[Dict[str, Any]] = []
    reject: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    scanned = 0
    waiting = 0

    for sym in symbols:
        ev = evaluate_symbol(sym)
        if not ev.get("success"):
            err = ev.get("error") or "fail"
            errors.append({"symbol": sym, "error": err})
            if "not harvested" in str(err):
                waiting += 1
            continue
        scanned += 1
        board = ev.get("board")
        if (
            board == "REJECT"
            and ev.get("zone") == "MID"
            and not ev.get("reclaim")
            and not ev.get("div_live")
        ):
            # Mid-range names with no live divergence are not a desk row
            continue
        if board == "TRADE":
            trade.append(ev)
        elif board == "WATCH":
            watch.append(ev)
        else:
            reject.append(ev)

    def _key(r: Dict[str, Any]):
        return (-(r.get("desk_score") or 0), r.get("name") or "")

    trade.sort(key=_key)
    watch.sort(key=_key)
    reject.sort(key=_key)

    harvest = {}
    try:
        harvest = store.status()
    except Exception:
        harvest = {}

    return {
        "success": True,
        "scanned": scanned,
        "universe": len(symbols),
        "trade": trade,
        "watch": watch,
        "reject": reject,
        "counts": {
            "trade": len(trade),
            "watch": len(watch),
            "reject": len(reject),
            "oversold": sum(
                1 for r in trade + watch if r.get("thesis") == "BOUNCE"
            ),
            "overbought": sum(
                1 for r in trade + watch if r.get("thesis") == "FADE"
            ),
            "waiting_harvest": waiting,
        },
        "harvest": {
            "symbols": harvest.get("symbols"),
            "history_15_fresh": harvest.get("history_15_fresh"),
            "freshest_age": harvest.get("freshest_age"),
            "redis": harvest.get("redis"),
        },
        "errors": errors[:30] if errors else None,
        "error_count": len(errors),
        "rules": {
            "rsi_period": RSI_PERIOD,
            "oversold": RSI_OS,
            "overbought": RSI_OB,
            "reclaim_preferred": True,
            "stuck_requires_p": RECLAIM_OR_STUCK_P,
            "mtf_hard_gate": True,
            "max_pain": False,
            "tf": ["15", "60"],
            "rsi5": False,
            "description": (
                "15m RSI(14) extreme + derived 1H. TRADE needs reclaim "
                f"(or P≥{RECLAIM_OR_STUCK_P:.0f}), bullish OC for bounce / "
                "bearish OC for fade, 4H allowed_side. Classic RSI divergence "
                "is a boost/tag, never a ticket alone."
            ),
        },
        "source": source,
        "limit": limit,
    }


def rsi_snapshot(symbol: str) -> Dict[str, Any]:
    """15m + derived 1H RSI from the harvest book. Empty dict if no 15m."""
    from app.services import symbol_store as store

    m15 = store.get_history(symbol, "15", min_bars=RSI_PERIOD + 5) or []
    if len(m15) < RSI_PERIOD + 5:
        return {}
    h1 = store.get_history(symbol, "60", min_bars=RSI_PERIOD + 5) or []
    if len(h1) < RSI_PERIOD + 5:
        h1 = store.aggregate_ohlcv(m15, 60)
    r15s = rsi_wilder(m15)
    r60s = rsi_wilder(h1) if h1 else []
    rsi15 = last_rsi(r15s)
    rsi60 = last_rsi(r60s)
    prev15 = None
    for v in reversed(r15s[:-1]):
        if v is not None:
            prev15 = round(float(v), 2)
            break
    ev = classify_rsi_event(prev15, rsi15)
    div15 = classify_divergence(m15, r15s, tf=15)
    div60 = classify_divergence(h1, r60s, tf=60, period_minutes=60) if h1 else {}
    live = bool(div15.get("live"))
    return {
        "rsi15": rsi15,
        "rsi60": rsi60,
        "event": ev.get("event"),
        "zone": ev.get("zone"),
        "reclaim": bool(ev.get("reclaim")),
        "fresh": bool(ev.get("fresh")),
        "div_type": div15.get("type") if live else None,
        "div_event": div15.get("event") if live else None,
        "div_live": live,
        "div_fresh": bool(div15.get("fresh")),
        "div_bars_ago": div15.get("bars_ago"),
        "div_rsi_gap": div15.get("rsi_gap"),
        "div_price_l1": div15.get("price_l1"),
        "div_price_l2": div15.get("price_l2"),
        "div_rsi_l1": div15.get("rsi_l1"),
        "div_rsi_l2": div15.get("rsi_l2"),
        "div60_type": div60.get("type") if (div60 or {}).get("live") else None,
    }


def _radar_direction(row: Dict[str, Any]) -> str:
    d = (row.get("direction") or "").upper()
    if d in ("BULLISH", "BEARISH"):
        return d
    sig = row.get("signal") or {}
    if isinstance(sig, dict):
        d = (sig.get("direction") or "").upper()
        if d in ("BULLISH", "BEARISH"):
            return d
    if (row.get("process_direction") or "").upper() in ("BULLISH", "BEARISH"):
        return str(row.get("process_direction")).upper()
    if row.get("type") == "CE":
        return "BULLISH"
    if row.get("type") == "PE":
        return "BEARISH"
    return "NEUTRAL"


def weight_radar_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stack Flow Radar (LIS/grade/composite) with RSI + OC permission + 4H.
    Does not change LIS or grade. Writes desk_score 0–100.
    """
    if not row or not row.get("symbol"):
        return row
    symbol = row["symbol"]
    direction = _radar_direction(row)
    lis = _f(row.get("lis"))
    composite = _f(row.get("composite_score") or lis)
    grade = row.get("grade") or "C"

    rsi = rsi_snapshot(symbol)
    rsi15 = rsi.get("rsi15")
    rsi60 = rsi.get("rsi60")
    zone = rsi.get("zone")
    event = rsi.get("event") or "NONE"

    perm: Dict[str, Any] = {"p": 0.0, "hard_fail": [], "hits": [], "miss": ["no direction"]}
    gate: Dict[str, Any] = {"ok": True, "hard": False, "reason": "SKIP", "allowed_side": "NONE"}
    if direction in ("BULLISH", "BEARISH"):
        try:
            perm = permission_from_snapshot(symbol, direction, spot=_f(row.get("spot")))
        except Exception:
            perm = {"p": 0.0, "hard_fail": [], "hits": [], "miss": ["perm fail"]}
        try:
            mtf = mtf_for_symbol(symbol)
            gate = mtf_gate(direction, mtf)
        except Exception:
            pass

    p = _f(perm.get("p"))
    hard = list(perm.get("hard_fail") or [])

    radar_w = min(32.0, composite * 0.28)
    lis_w = min(18.0, lis * 0.18)
    grade_w = {"A+": 10.0, "A": 8.0, "B": 4.0, "C": 0.0}.get(str(grade), 0.0)

    agrees = (
        rsi15 is not None
        and (
            (direction == "BULLISH" and rsi15 <= RSI_OS)
            or (direction == "BEARISH" and rsi15 >= RSI_OB)
        )
    )
    fights = (
        rsi15 is not None
        and (
            (direction == "BULLISH" and rsi15 >= RSI_OB)
            or (direction == "BEARISH" and rsi15 <= RSI_OS)
        )
    )
    htf_same = (
        rsi60 is not None
        and (
            (direction == "BULLISH" and rsi60 <= RSI_HTF_OS_SOFT)
            or (direction == "BEARISH" and rsi60 >= RSI_HTF_OB_SOFT)
        )
    )
    rsi_w = 0.0
    if agrees:
        rsi_w += 14.0
        if htf_same:
            rsi_w += 8.0
        if event in ("RECLAIM_OS", "RECLAIM_OB"):
            rsi_w += 8.0
        elif event in ("ENTER_OS", "ENTER_OB"):
            rsi_w += 4.0
    elif fights:
        rsi_w -= 14.0
        if htf_same:
            rsi_w -= 6.0

    div_type = rsi.get("div_type") if rsi.get("div_live") else None
    div_fresh = bool(rsi.get("div_fresh")) and bool(div_type)
    div60_type = rsi.get("div60_type")
    div_w = 0.0
    if div_type == "BULL_DIV" and direction == "BULLISH":
        div_w += 8.0
        if div60_type == "BULL_DIV":
            div_w += 4.0
        if div_fresh:
            div_w += 4.0
    elif div_type == "BEAR_DIV" and direction == "BEARISH":
        div_w += 8.0
        if div60_type == "BEAR_DIV":
            div_w += 4.0
        if div_fresh:
            div_w += 4.0
    elif div_type == "BEAR_DIV" and direction == "BULLISH":
        div_w -= 10.0
    elif div_type == "BULL_DIV" and direction == "BEARISH":
        div_w -= 10.0
    rsi_w += div_w

    oc_w = min(22.0, p * 0.22)
    if "OC_CONFLICT" in hard or "FUTURES_OPPOSITE" in hard:
        oc_w = min(oc_w, 4.0)

    if gate.get("hard"):
        mtf_w = -18.0
    elif gate.get("reason") == "ALIGNED":
        mtf_w = 10.0
    else:
        mtf_w = 0.0

    loc_w = min(6.0, _f(row.get("location_score")) * 0.55)
    lock_w = 0.0
    if row.get("process_locked"):
        pd = (row.get("process_direction") or "").upper()
        if pd == direction or not pd:
            lock_w = 6.0

    vwap_w = 0.0
    try:
        from app.services import symbol_store as store

        m15 = store.get_history(symbol, "15", min_bars=8) or []
        vwap = session_vwap(m15) if m15 else None
        spot = _f(row.get("spot"))
        if vwap and spot > 0 and direction in ("BULLISH", "BEARISH"):
            agree = (
                (direction == "BULLISH" and spot >= vwap)
                or (direction == "BEARISH" and spot <= vwap)
            )
            vwap_w = 6.0 if agree else -8.0
            row["vwap"] = round(vwap, 2)
            row["vwap_dev_pct"] = round((spot - vwap) / vwap * 100.0, 3)
            row["vwap_agree"] = agree
    except Exception:
        pass

    desk = radar_w + lis_w + grade_w + rsi_w + oc_w + mtf_w + loc_w + lock_w + vwap_w
    desk = max(0.0, min(100.0, desk))
    if gate.get("hard"):
        desk = min(desk, 38.0)
    if "OC_CONFLICT" in hard or "FUTURES_OPPOSITE" in hard:
        desk = min(desk, 42.0)
    if vwap_w < 0:
        desk = min(desk, 50.0)

    if agrees and p >= 60 and not gate.get("hard") and "OC_CONFLICT" not in hard:
        align = "STACK"
        thesis = "BOUNCE" if direction == "BULLISH" else "FADE"
    elif fights:
        align = "FIGHT"
        thesis = "LATE" if direction == "BULLISH" else "CATCH"
    elif gate.get("hard"):
        align = "VETO"
        thesis = "VETO"
    else:
        align = "FLOW"
        thesis = "FLOW"

    row["desk_score"] = round(desk, 1)
    row["desk_align"] = align
    row["desk_thesis"] = thesis
    row["rsi15"] = rsi15
    row["rsi60"] = rsi60
    row["rsi_event"] = event
    row["rsi_zone"] = zone
    row["rsi_div"] = div_type
    row["rsi_div_event"] = rsi.get("div_event") if div_type else None
    row["rsi_div_fresh"] = div_fresh
    row["rsi_div_bars_ago"] = rsi.get("div_bars_ago") if div_type else None
    row["rsi_div_rsi_gap"] = rsi.get("div_rsi_gap") if div_type else None
    row["rsi_div_price_l1"] = rsi.get("div_price_l1") if div_type else None
    row["rsi_div_price_l2"] = rsi.get("div_price_l2") if div_type else None
    row["rsi_div_rsi_l1"] = rsi.get("div_rsi_l1") if div_type else None
    row["rsi_div_rsi_l2"] = rsi.get("div_rsi_l2") if div_type else None
    row["oc_permission"] = round(p, 1)
    row["oc_hits"] = perm.get("hits") or []
    row["mtf_allowed"] = gate.get("allowed_side")
    row["h4_bias"] = gate.get("h4_bias")
    row["mtf_gate"] = gate.get("reason")
    row["desk_parts"] = {
        "radar": round(radar_w, 1),
        "lis": round(lis_w, 1),
        "grade": grade_w,
        "rsi": round(rsi_w, 1),
        "oc": round(oc_w, 1),
        "mtf": mtf_w,
        "location": round(loc_w, 1),
        "lock": lock_w,
        "vwap": round(vwap_w, 1),
        "div": round(div_w, 1),
    }
    return row


def weight_radar_rows(rows: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows or []:
        try:
            out.append(weight_radar_row(dict(row)))
        except Exception:
            out.append(row)
    out.sort(
        key=lambda x: (
            float(x.get("desk_score") or 0),
            float(x.get("composite_score") or 0),
            float(x.get("lis") or 0),
        ),
        reverse=True,
    )
    return out


def evaluate_divergence_symbol(symbol: str, *, tf: str = "15") -> Dict[str, Any]:
    """Classic RSI divergence on stored 15m or daily. No Fyers."""
    from app.services import symbol_store as store

    tf_key = "D" if str(tf).upper() in ("D", "1D", "DAY", "DAILY", "1") else "15"
    period = 1440 if tf_key == "D" else 15
    tf_code = 1440 if tf_key == "D" else 15
    fresh_bars = 1 if tf_key == "D" else 3
    stale_bars = 5 if tf_key == "D" else 8
    min_bars = RSI_PERIOD + 8

    candles = store.get_history(symbol, tf_key, min_bars=min_bars) or []
    if len(candles) < min_bars:
        return {
            "success": False,
            "error": f"{tf_key} book not harvested yet",
            "symbol": symbol,
            "tf": tf_key,
        }

    series = rsi_wilder(candles)
    rsi_now = last_rsi(series)
    div = classify_divergence(
        candles,
        series,
        tf=tf_code,
        period_minutes=period,
        fresh_bars=fresh_bars,
        stale_bars=stale_bars,
    )
    if not div.get("live") or not div.get("type"):
        return {
            "success": True,
            "symbol": symbol,
            "name": _name(symbol),
            "tf": tf_key,
            "board": "IGNORE",
            "rsi": rsi_now,
            "div_live": False,
            "div_type": None,
            "event": div.get("event"),
        }

    side = "BULLISH" if div.get("type") == "BULL_DIV" else "BEARISH"
    snap = store.get(symbol) or {}
    spot = _f((snap.get("spot") or {}).get("ltp") or candles[-1].get("close"))
    mtf = mtf_for_symbol(symbol)
    gate = mtf_gate(side, mtf)
    perm = permission_from_snapshot(symbol, side, snap=snap, spot=spot)
    p = float(perm.get("p") or 0)
    hard = list(perm.get("hard_fail") or [])
    d_score = divergence_score(div, None, rsi15=rsi_now, near_vwap=near_session_vwap(spot, session_vwap(candles if tf_key == "15" else [])))
    desk = round(0.35 * d_score + 0.65 * p, 1) if d_score else round(0.40 * 0 + 0.60 * p, 1)

    board = "WATCH"
    reason = "live divergence"
    if gate.get("hard"):
        board, reason = "REJECT", gate.get("detail") or gate.get("reason") or "4H opposite"
    elif "OC_CONFLICT" in hard or "FUTURES_OPPOSITE" in hard:
        board, reason = "REJECT", "; ".join(perm.get("miss") or hard) or "OC knife"
    elif side == "BEARISH":
        bias = ((perm.get("buildup") or {}).get("bias") or "").upper()
        if bias == "BULLISH" and "OC_CONFLICT" not in hard:
            board, reason = "WATCH", "Divergence but chain still bullish — do not fade"
    if board != "REJECT":
        extreme = (
            (side == "BULLISH" and rsi_now is not None and rsi_now <= BULL_RSI_MAX)
            or (side == "BEARISH" and rsi_now is not None and rsi_now >= BEAR_RSI_MIN)
        )
        if p < P_AVOID:
            board, reason = "REJECT", f"Permission {p:.0f} < {P_AVOID:.0f}"
        elif gate.get("soft"):
            board, reason = "WATCH", "4H mixed — divergence watch"
        elif (div.get("fresh") or extreme) and p >= P_SETUP and not gate.get("hard"):
            board, reason = "TRADE", "SETUP"
        else:
            board, reason = "WATCH", "divergence, wait reclaim / stronger OC"

    ticket = None
    grade = None
    if board == "TRADE":
        fake_cross = {
            "ema200": None,
            "ltp": spot,
            "volume_ratio": _rel_vol(candles),
            "bars_ago": div.get("bars_ago") or 0,
            "fresh_label": div.get("event"),
        }
        closes = [_f(c.get("close")) for c in candles]
        e20 = next((v for v in reversed(_ema(closes, 20)) if v is not None), None)
        fake_cross["ema200"] = e20
        ticket = build_ticket(
            symbol=symbol,
            cross_type=side,
            cross=fake_cross,
            perm=perm,
            mtf=mtf,
            adx=compute_adx(candles),
            vwap=session_vwap(candles) if tf_key == "15" else None,
            atr=compute_atr(candles),
        )
        if ticket:
            ticket["trigger"] = (
                f"{tf_key} {div.get('event')} · RSI {rsi_now} · "
                f"price {div.get('price_l1')}→{div.get('price_l2')} · "
                f"{div.get('bars_ago')} bars ago"
            )
            grade = "SETUP"
        else:
            board, reason = "WATCH", "Permission ok but no vehicle"

    return {
        "success": True,
        "symbol": symbol,
        "name": _name(symbol),
        "tf": tf_key,
        "ltp": spot,
        "side": side,
        "thesis": "BOUNCE" if side == "BULLISH" else "FADE",
        "rsi": rsi_now,
        "event": div.get("event"),
        "div_type": div.get("type"),
        "div_live": True,
        "div_fresh": bool(div.get("fresh")),
        "div_bars_ago": div.get("bars_ago"),
        "div_rsi_gap": div.get("rsi_gap"),
        "div_price_l1": div.get("price_l1"),
        "div_price_l2": div.get("price_l2"),
        "div_rsi_l1": div.get("rsi_l1"),
        "div_rsi_l2": div.get("rsi_l2"),
        "permission": perm.get("p"),
        "permission_hits": perm.get("hits") or [],
        "permission_miss": perm.get("miss") or [],
        "hard_fail": hard,
        "h4_bias": gate.get("h4_bias") or mtf.get("h4_bias"),
        "mtf_allowed": gate.get("allowed_side"),
        "mtf_gate": gate.get("reason"),
        "desk_score": desk,
        "div_score": d_score,
        "board": board,
        "board_reason": reason,
        "grade": grade,
        "ticket": ticket,
    }


def scan_divergence_book(*, tf: str = "15", source: str = "full", limit: int = 200) -> Dict[str, Any]:
    """CPU scan of live classic divergences on harvested 15m or daily."""
    from app.services import symbol_store as store
    from app.services.fno_stocks import TOP_FNO_STOCKS

    tf_key = "D" if str(tf).upper() in ("D", "1D", "DAY", "DAILY", "1") else "15"
    if source == "top":
        symbols = filter_valid_symbols(list(TOP_FNO_STOCKS))[:limit]
    else:
        symbols = filter_valid_symbols(list(FNO_STOCKS))[:limit]

    trade: List[Dict[str, Any]] = []
    watch: List[Dict[str, Any]] = []
    reject: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    scanned = 0
    waiting = 0

    for sym in symbols:
        ev = evaluate_divergence_symbol(sym, tf=tf_key)
        if not ev.get("success"):
            err = ev.get("error") or "fail"
            errors.append({"symbol": sym, "error": err})
            if "not harvested" in str(err):
                waiting += 1
            continue
        scanned += 1
        board = ev.get("board")
        if board == "IGNORE" or not ev.get("div_live"):
            continue
        if board == "TRADE":
            trade.append(ev)
        elif board == "WATCH":
            watch.append(ev)
        else:
            reject.append(ev)

    def _key(r: Dict[str, Any]):
        return (-(r.get("desk_score") or 0), r.get("name") or "")

    trade.sort(key=_key)
    watch.sort(key=_key)
    reject.sort(key=_key)
    harvest = {}
    try:
        harvest = store.status()
    except Exception:
        harvest = {}
    return {
        "success": True,
        "tf": tf_key,
        "scanned": scanned,
        "universe": len(symbols),
        "trade": trade,
        "watch": watch,
        "reject": reject,
        "counts": {
            "trade": len(trade),
            "watch": len(watch),
            "reject": len(reject),
            "bull": sum(1 for r in trade + watch if r.get("thesis") == "BOUNCE"),
            "bear": sum(1 for r in trade + watch if r.get("thesis") == "FADE"),
            "waiting_harvest": waiting,
        },
        "harvest": {
            "symbols": harvest.get("symbols"),
            "history_15_fresh": harvest.get("history_15_fresh"),
            "freshest_age": harvest.get("freshest_age"),
            "redis": harvest.get("redis"),
        },
        "errors": errors[:30] if errors else None,
        "error_count": len(errors),
        "rules": {
            "rsi_period": RSI_PERIOD,
            "tf": tf_key,
            "classic_only": True,
            "description": (
                f"{tf_key} Wilder RSI(14) classic divergence. TRADE needs live div + "
                "OC permission + 4H not opposite. No Fyers."
            ),
        },
        "source": source,
        "limit": limit,
    }
