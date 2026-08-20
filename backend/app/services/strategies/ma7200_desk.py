"""
7/200 desk: permission, MTF gate, ticket.

The 15m cross is only a trigger. This module decides whether a ticket
may exist: 4H allowed_side, option/futures sponsorship, location, vehicle.
CPU-only on the harvest snapshot. No Fyers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

ADX_PERIOD = 14
ADX_TRADE_MIN = 20.0
NEAR_GAP_PCT = 0.25
BARS2_MAX_EXT_PCT = 1.2
BARS2_MIN_P = 70.0
P_AVOID = 40.0
P_SETUP = 60.0
P_A = 75.0
T_SETUP = 55.0
ATM_VOL_FLOOR = 40.0
ATM_OI_FLOOR = 200.0
IV_SPREAD_ABS = 40.0


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _bar_ts(c: Dict[str, Any]) -> Optional[int]:
    ts = c.get("timestamp")
    if ts is not None:
        try:
            return int(ts)
        except (TypeError, ValueError):
            pass
    dt = c.get("datetime")
    if dt:
        try:
            return int(datetime.fromisoformat(str(dt).replace("Z", "+00:00")).timestamp())
        except Exception:
            pass
    return None


def _ema(values: List[float], period: int) -> List[Optional[float]]:
    n = len(values)
    out: List[Optional[float]] = [None] * n
    if n < period or period < 2:
        return out
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    for i in range(period, n):
        seed = values[i] * k + seed * (1.0 - k)
        out[i] = seed
    return out


def compute_atr(candles: List[Dict], period: int = ADX_PERIOD) -> Optional[float]:
    if len(candles) < period + 2:
        return None
    trs: List[float] = []
    for i in range(1, len(candles)):
        h = _f(candles[i].get("high"))
        l = _f(candles[i].get("low"))
        pc = _f(candles[i - 1].get("close"))
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def compute_adx(candles: List[Dict], period: int = ADX_PERIOD) -> Optional[float]:
    """Wilder ADX. Returns latest ADX or None if not enough bars."""
    n = len(candles)
    if n < period * 2 + 2:
        return None
    plus_dm: List[float] = []
    minus_dm: List[float] = []
    trs: List[float] = []
    for i in range(1, n):
        h = _f(candles[i].get("high"))
        l = _f(candles[i].get("low"))
        ph = _f(candles[i - 1].get("high"))
        pl = _f(candles[i - 1].get("low"))
        pc = _f(candles[i - 1].get("close"))
        up = h - ph
        dn = pl - l
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    def _wilder(xs: List[float]) -> List[float]:
        if len(xs) < period:
            return []
        acc = sum(xs[:period])
        out = [acc]
        for x in xs[period:]:
            acc = acc - acc / period + x
            out.append(acc)
        return out

    str_ = _wilder(trs)
    sp = _wilder(plus_dm)
    sm = _wilder(minus_dm)
    if not str_ or len(str_) != len(sp):
        return None
    dx: List[float] = []
    for t, p, m in zip(str_, sp, sm):
        if t <= 1e-12:
            continue
        pdi = 100.0 * p / t
        mdi = 100.0 * m / t
        s = pdi + mdi
        dx.append(0.0 if s <= 1e-12 else 100.0 * abs(pdi - mdi) / s)
    if len(dx) < period:
        return None
    adx = sum(dx[:period]) / period
    for x in dx[period:]:
        adx = (adx * (period - 1) + x) / period
    return round(adx, 2)


def session_vwap(candles: List[Dict]) -> Optional[float]:
    today = datetime.now(IST).date()
    sess: List[Dict] = []
    for c in candles:
        ts = _bar_ts(c)
        if ts:
            try:
                if datetime.fromtimestamp(ts, tz=IST).date() == today:
                    sess.append(c)
            except Exception:
                pass
    if len(sess) < 3:
        sess = candles[-26:]
    num = den = 0.0
    for c in sess:
        h, l, cl = _f(c.get("high")), _f(c.get("low")), _f(c.get("close"))
        vol = _f(c.get("volume"))
        tp = (h + l + cl) / 3.0
        num += tp * vol
        den += vol
    if den <= 0:
        return None
    return num / den


def ema200_slope_aligned(candles: List[Dict], slow: int, side: str) -> bool:
    closes = [_f(c.get("close")) for c in candles]
    series = _ema(closes, slow)
    vals = [v for v in series if v is not None]
    if len(vals) < 6:
        return True  # unknown — do not hard-kill
    delta = vals[-1] - vals[-5]
    if side == "BULLISH":
        return delta >= 0
    return delta <= 0


def score_near_cross(
    candles: List[Dict],
    *,
    fast: int = 7,
    slow: int = 200,
) -> Optional[Dict[str, Any]]:
    """7 approaching 200, not yet crossed. Watch only."""
    if not candles or len(candles) < slow + 6:
        return None
    closes = [_f(c.get("close")) for c in candles]
    vols = [_f(c.get("volume")) for c in candles]
    e7 = _ema(closes, fast)
    e200 = _ema(closes, slow)
    i = len(closes) - 1
    a, b = e7[i], e200[i]
    ap, bp = e7[i - 1], e200[i - 1]
    if None in (a, b, ap, bp):
        return None
    # already crossed this bar
    if (ap <= bp and a > b) or (ap >= bp and a < b):
        return None
    px = closes[i] or 1.0
    gap = abs(a - b) / max(abs(px), 1e-9) * 100.0
    gap_prev = abs(ap - bp) / max(abs(px), 1e-9) * 100.0
    if gap > NEAR_GAP_PCT:
        return None
    shrinking = gap < gap_prev - 1e-6 or gap < NEAR_GAP_PCT * 0.6
    if not shrinking:
        return None
    side = "BULLISH" if a <= b else "BEARISH"
    rising = i >= 2 and vols[i] >= vols[i - 1] * 0.95
    score = 40.0
    score += max(0.0, (NEAR_GAP_PCT - gap) / NEAR_GAP_PCT * 30.0)
    if rising:
        score += 10.0
    if shrinking:
        score += 10.0
    return {
        "kind": "NEAR",
        "cross_type": side,
        "gap_pct": round(gap, 3),
        "gap_prev_pct": round(gap_prev, 3),
        "ema7": round(float(a), 2),
        "ema200": round(float(b), 2),
        "ltp": px,
        "volume_rising": rising,
        "approach_score": round(min(100.0, score), 1),
        "bars_ago": None,
        "freshness": "NEAR",
        "fresh_label": "NEAR",
    }


def mtf_for_symbol(symbol: str) -> Dict[str, Any]:
    from app.services import symbol_store as store
    from app.services.mtf_service import get_mtf_service

    m15 = store.get_history(symbol, "15", min_bars=20) or []
    daily = store.get_history(symbol, "D", min_bars=10) or []
    if not m15 and not daily:
        return {"ok": False, "allowed_side": "NONE", "h4_bias": "MIXED"}
    try:
        packed = get_mtf_service().evaluate(
            symbol, daily_candles=daily or None, m15_candles=m15 or None
        )
        packed["ok"] = bool(packed.get("ok") or packed.get("h4_bias") in ("BULLISH", "BEARISH"))
        return packed
    except Exception:
        return {"ok": False, "allowed_side": "NONE", "h4_bias": "MIXED"}


def mtf_gate(cross_type: str, mtf: Dict[str, Any]) -> Dict[str, Any]:
    """
    Hard: 4H firmly opposite the 7/200 side → no LONG/SHORT ticket.
    Soft: 4H mixed / unknown → not A-SETUP.
    """
    want = "LONG" if (cross_type or "").upper() == "BULLISH" else "SHORT"
    h4 = (mtf.get("h4_bias") or "").upper()
    allowed = (mtf.get("allowed_side") or "NONE").upper()
    daily_veto = bool(mtf.get("daily_veto"))
    opposite = "SHORT" if want == "LONG" else "LONG"
    h4_opposite = (want == "LONG" and h4 == "BEARISH") or (
        want == "SHORT" and h4 == "BULLISH"
    )

    if daily_veto:
        return {
            "ok": False,
            "hard": True,
            "reason": "DAILY_VETO",
            "allowed_side": allowed,
            "h4_bias": h4,
            "want": want,
        }
    if h4_opposite or allowed == opposite:
        return {
            "ok": False,
            "hard": True,
            "reason": "MTF_ALLOWED_SIDE",
            "detail": f"4H {h4 or '—'} blocks {want} (allowed={allowed})",
            "allowed_side": allowed,
            "h4_bias": h4,
            "want": want,
        }
    if allowed == want:
        return {
            "ok": True,
            "hard": False,
            "reason": "ALIGNED",
            "allowed_side": allowed,
            "h4_bias": h4,
            "want": want,
        }
    return {
        "ok": True,
        "hard": False,
        "soft": True,
        "reason": "4H_MIXED",
        "detail": "4H not firmly aligned — cap grade",
        "allowed_side": allowed,
        "h4_bias": h4 or "MIXED",
        "want": want,
    }


def _leg(row: Dict, side: str) -> Dict:
    raw = row.get(side) or row.get("call" if side == "CE" else "put") or {}
    return raw if isinstance(raw, dict) else {}


def _atm_iv(chain_rows: List[Dict], atm: Optional[float]) -> Optional[float]:
    if not chain_rows or atm is None:
        return None
    best = None
    best_d = 1e18
    for r in chain_rows:
        st = _f(r.get("strike_price"))
        d = abs(st - float(atm))
        if d < best_d:
            best_d = d
            best = r
    if not best:
        return None
    ivs = []
    for key in ("call", "put"):
        iv = (best.get(key) or {}).get("iv")
        if iv is not None and _f(iv) > 0:
            ivs.append(_f(iv))
    if not ivs:
        return None
    return sum(ivs) / len(ivs)


def _atm_liquidity(chain_rows: List[Dict], atm: Optional[float]) -> Dict[str, float]:
    empty = {"volume": 0.0, "oi": 0.0}
    if not chain_rows or atm is None:
        return empty
    best = min(
        chain_rows,
        key=lambda r: abs(_f(r.get("strike_price")) - float(atm)),
    )
    vol = oi = 0.0
    for key in ("call", "put"):
        leg = best.get(key) or {}
        vol += _f(leg.get("volume"))
        oi += _f(leg.get("oi"))
    return {"volume": vol, "oi": oi}


def permission_from_snapshot(
    symbol: str,
    cross_type: str,
    *,
    snap: Optional[Dict[str, Any]] = None,
    chain_rows: Optional[List[Dict]] = None,
    spot: Optional[float] = None,
) -> Dict[str, Any]:
    """CE/PE 4-box + futures 4-box. Max pain is not a hit."""
    from app.services import symbol_store as store
    from app.services.option_analytics import (
        analyze_chain_buildups,
        compute_professional_pcr,
        compute_structure_walls,
    )

    snap = snap or store.get(symbol) or {}
    oc = None
    if chain_rows is None:
        oc = store.get_chain(symbol, 14)
        chain_rows = (oc or {}).get("chain") or []
    if not chain_rows:
        ch = snap.get("chain") or {}
        chain_rows = ch.get("rows") or ch.get("chain") or []
    spot = _f(
        spot
        or (oc or {}).get("spot_price")
        or (snap.get("spot") or {}).get("ltp")
        or (snap.get("chain") or {}).get("spot_price")
    )
    atm = (oc or {}).get("atm_strike") or (snap.get("chain") or {}).get("atm_strike")
    if atm is None and chain_rows and spot:
        atm = min(
            (_f(r.get("strike_price")) for r in chain_rows if r.get("strike_price") is not None),
            key=lambda s: abs(s - spot),
            default=None,
        )

    hits: List[Dict[str, Any]] = []
    miss: List[str] = []
    hard_fail: List[str] = []
    p = 0.0

    if not chain_rows or spot <= 0:
        return {
            "p": 0.0,
            "hits": [],
            "miss": ["no stored chain"],
            "hard_fail": ["NO_CHAIN"],
            "buildup": {},
            "walls": {},
            "futures": snap.get("futures") or {},
            "oi_pcr": None,
            "atm_iv": None,
            "liquid": False,
        }

    buildup = analyze_chain_buildups(chain_rows, spot, atm=atm, band=2)
    pcr = compute_professional_pcr(chain_rows, spot=spot, atm=atm, band=3)
    walls = compute_structure_walls(chain_rows, spot)
    band = buildup.get("atm_band") or []
    side = (cross_type or "").upper()
    fut = snap.get("futures") or {}

    def _band_has(leg: str, state: str, *, above_atm: Optional[bool]) -> List[str]:
        found = []
        for row in band:
            st = _f(row.get("strike"))
            body = (row.get(leg) or {}).get("state") or ""
            if state not in body:
                continue
            if atm is not None and above_atm is True and st < float(atm) - 1e-6:
                continue
            if atm is not None and above_atm is False and st > float(atm) + 1e-6:
                continue
            found.append(f"{int(st) if st == int(st) else st} {leg[:2].upper()}: {body}")
        return found

    # --- futures ---
    fut_state = (fut.get("state") or "").upper()
    fut_dir = (fut.get("direction") or "").upper()
    if fut_state in ("LONG_BUILDUP",) and side == "BULLISH":
        p += 25
        hits.append({"rule": "Futures long buildup", "detail": fut.get("label") or fut_state, "w": 25})
    elif fut_state in ("SHORT_BUILDUP",) and side == "BEARISH":
        p += 25
        hits.append({"rule": "Futures short buildup", "detail": fut.get("label") or fut_state, "w": 25})
    elif fut_state in ("SHORT_COVERING",) and side == "BULLISH":
        p += 8
        hits.append({"rule": "Futures short covering (weak)", "detail": fut_state, "w": 8})
    elif fut_state in ("LONG_UNWINDING",) and side == "BEARISH":
        p += 8
        hits.append({"rule": "Futures long unwinding (weak)", "detail": fut_state, "w": 8})
    elif fut_state in ("LONG_BUILDUP",) and side == "BEARISH":
        hard_fail.append("FUTURES_OPPOSITE")
        miss.append(f"Futures long buildup vs bearish cross")
    elif fut_state in ("SHORT_BUILDUP",) and side == "BULLISH":
        hard_fail.append("FUTURES_OPPOSITE")
        miss.append(f"Futures short buildup vs bullish cross")
    elif not fut_state or fut_state in ("UNKNOWN", "CHURN"):
        miss.append("No futures 4-box (not required)")

    # --- primary CE/PE story ---
    if side == "BULLISH":
        ce_lb = _band_has("call", "Long Buildup", above_atm=True)
        for row in band:
            if row.get("is_atm") and "Long Buildup" in ((row.get("call") or {}).get("state") or ""):
                ce_lb.append(f"{row.get('strike')} CE ATM Long Buildup")
        pe_w = _band_has("put", "Short Buildup", above_atm=False)
        pe_sc = _band_has("put", "Short Covering", above_atm=False)
        primary = False
        if ce_lb or int(buildup.get("strong_long_ce") or 0) > 0:
            p += 18
            hits.append({"rule": "CE long buildup ATM/+OTM", "detail": "; ".join(ce_lb[:3]) or "strong CE LB", "w": 18})
            primary = True
        else:
            miss.append("No CE long buildup ATM/+OTM")
        if pe_w or int(buildup.get("strong_short_pe") or 0) > 0:
            p += 18 if not primary else 12
            hits.append({"rule": "PE writing ATM/below", "detail": "; ".join(pe_w[:3]) or "PE short buildup", "w": 18})
            primary = True
        elif pe_sc:
            p += 6
            hits.append({"rule": "PE short covering (weak support)", "detail": "; ".join(pe_sc[:2]), "w": 6})
        else:
            miss.append("No PE writing ATM/below")
        if not primary:
            miss.append("No primary bullish CE/PE story")

        pe_lb = _band_has("put", "Long Buildup", above_atm=False)
        ce_w = _band_has("call", "Short Buildup", above_atm=True)
        if pe_lb and ce_w:
            hard_fail.append("OC_CONFLICT")
            miss.append("Conflict: PE long buildup + CE writing")
        elif buildup.get("bias") == "BEARISH" and int(buildup.get("strong_long_pe") or 0) >= 2:
            hard_fail.append("OC_CONFLICT")
            miss.append(buildup.get("note") or "Bearish chain vs bullish cross")
    else:
        pe_lb = _band_has("put", "Long Buildup", above_atm=False)
        for row in band:
            if row.get("is_atm") and "Long Buildup" in ((row.get("put") or {}).get("state") or ""):
                pe_lb.append(f"{row.get('strike')} PE ATM Long Buildup")
        ce_w = _band_has("call", "Short Buildup", above_atm=True)
        primary = False
        if pe_lb or int(buildup.get("strong_long_pe") or 0) > 0:
            p += 18
            hits.append({"rule": "PE long buildup ATM/below", "detail": "; ".join(pe_lb[:3]) or "strong PE LB", "w": 18})
            primary = True
        else:
            miss.append("No PE long buildup ATM/below")
        if ce_w or int(buildup.get("strong_short_ce") or 0) > 0:
            p += 18 if not primary else 12
            hits.append({"rule": "CE writing ATM/above", "detail": "; ".join(ce_w[:3]) or "CE short buildup", "w": 18})
            primary = True
        else:
            miss.append("No CE writing ATM/above")
        if not primary:
            miss.append("No primary bearish CE/PE story")

        ce_lb = _band_has("call", "Long Buildup", above_atm=True)
        pe_w = _band_has("put", "Short Buildup", above_atm=False)
        if ce_lb and pe_w:
            hard_fail.append("OC_CONFLICT")
            miss.append("Conflict: CE long buildup + PE writing")
        elif buildup.get("bias") == "BULLISH" and int(buildup.get("strong_long_ce") or 0) >= 2:
            hard_fail.append("OC_CONFLICT")
            miss.append(buildup.get("note") or "Bullish chain vs bearish cross")

    if not hard_fail:
        p += 15
        hits.append({"rule": "No opposite hard-fail", "detail": "CE/PE not fighting the cross", "w": 15})

    # walls as secondary location (not max pain)
    put_wall = walls.get("put_wall")
    call_wall = walls.get("call_wall")
    if side == "BULLISH" and put_wall and spot and float(put_wall) < spot:
        p += 8
        hits.append({"rule": "Put wall below spot", "detail": f"PE wall {put_wall}", "w": 8})
    elif side == "BEARISH" and call_wall and spot and float(call_wall) > spot:
        p += 8
        hits.append({"rule": "Call wall above spot", "detail": f"CE wall {call_wall}", "w": 8})
    else:
        miss.append("No supporting OI wall")

    # PCR change / ATM PCR — soft only, no 1.0 magic, no max pain
    oi_pcr = pcr.get("oi_pcr")
    atm_pcr = pcr.get("atm_oi_pcr")
    if side == "BULLISH" and atm_pcr and float(atm_pcr) >= 1.05:
        p += 5
        hits.append({"rule": "ATM PCR supportive (soft)", "detail": f"ATM PCR {float(atm_pcr):.2f}", "w": 5})
    elif side == "BEARISH" and atm_pcr and float(atm_pcr) <= 0.90:
        p += 5
        hits.append({"rule": "ATM PCR bearish (soft)", "detail": f"ATM PCR {float(atm_pcr):.2f}", "w": 5})

    liq = _atm_liquidity(chain_rows, atm)
    liquid = liq["volume"] >= ATM_VOL_FLOOR or liq["oi"] >= ATM_OI_FLOOR
    if liquid:
        p += 15
        hits.append({
            "rule": "ATM liquidity",
            "detail": f"vol {liq['volume']:.0f} OI {liq['oi']:.0f}",
            "w": 15,
        })
    else:
        miss.append(f"Thin ATM options (vol {liq['volume']:.0f} OI {liq['oi']:.0f})")
        hard_fail.append("NO_VEHICLE")

    p = max(0.0, min(100.0, p))
    if hard_fail:
        p = min(p, 35.0)

    return {
        "p": round(p, 1),
        "hits": hits,
        "miss": miss,
        "hard_fail": hard_fail,
        "buildup": {
            "primary_state": buildup.get("primary_state"),
            "bias": buildup.get("bias"),
            "note": buildup.get("note"),
            "conviction": buildup.get("conviction"),
        },
        "walls": {
            "put_wall": put_wall,
            "call_wall": call_wall,
            "put_wall_oi": walls.get("put_wall_oi"),
            "call_wall_oi": walls.get("call_wall_oi"),
        },
        "futures": {
            "state": fut_state or None,
            "direction": fut_dir or None,
            "ltp": fut.get("ltp"),
            "label": fut.get("label"),
        },
        "oi_pcr": oi_pcr,
        "atm_pcr": atm_pcr,
        "atm": atm,
        "spot": spot,
        "atm_iv": _atm_iv(chain_rows, atm),
        "liquid": liquid,
        "liquidity": liq,
    }


def _choose_vehicle(
    side: str,
    spot: float,
    atm: Optional[float],
    atm_iv: Optional[float],
    atr: Optional[float],
    walls: Dict[str, Any],
) -> Dict[str, Any]:
    atm_f = float(atm or spot or 0)
    iv = atm_iv
    # Fyers IV is percent. Elevated premium → defined-risk debit spread.
    use_spread = False
    why = "ATM outright (IV mid/low)"
    if iv is not None and iv >= IV_SPREAD_ABS:
        use_spread = True
        why = f"IV {iv:.1f} ≥ {IV_SPREAD_ABS:.0f} → debit spread"
    elif iv is not None and atr and spot:
        rv = atr / spot * 100.0  # 15m ATR as % of spot
        if rv > 0 and iv > max(28.0, rv * 40.0):
            use_spread = True
            why = f"IV {iv:.1f} rich vs 15m ATR {rv:.2f}% → debit spread"

    step = max(5.0, round(atm_f * 0.01 / 5) * 5) or 5.0
    # snap step to a round increment
    if atm_f >= 1000:
        step = max(10.0, round(atm_f * 0.008 / 10) * 10)
    elif atm_f >= 200:
        step = max(5.0, round(atm_f * 0.01 / 5) * 5)

    if side == "BULLISH":
        far = atm_f + step
        wall = walls.get("call_wall")
        if wall and float(wall) > atm_f:
            far = float(wall)
        if use_spread:
            return {
                "style": "DEBIT_SPREAD",
                "instrument": "CE",
                "strike": atm_f,
                "structure": f"{atm_f}/{far} Bull Call Spread",
                "why": why,
            }
        return {
            "style": "OUTRIGHT",
            "instrument": "CE",
            "strike": atm_f,
            "structure": f"{atm_f} CE",
            "why": why,
        }
    far = atm_f - step
    wall = walls.get("put_wall")
    if wall and float(wall) < atm_f:
        far = float(wall)
    if use_spread:
        return {
            "style": "DEBIT_SPREAD",
            "instrument": "PE",
            "strike": atm_f,
            "structure": f"{atm_f}/{far} Bear Put Spread",
            "why": why,
        }
    return {
        "style": "OUTRIGHT",
        "instrument": "PE",
        "strike": atm_f,
        "structure": f"{atm_f} PE",
        "why": why,
    }


def build_ticket(
    *,
    symbol: str,
    cross_type: str,
    cross: Dict[str, Any],
    perm: Dict[str, Any],
    mtf: Dict[str, Any],
    adx: Optional[float],
    vwap: Optional[float],
    atr: Optional[float],
) -> Optional[Dict[str, Any]]:
    if not perm.get("liquid") or "NO_VEHICLE" in (perm.get("hard_fail") or []):
        return None
    side = (cross_type or "").upper()
    spot = _f(perm.get("spot") or cross.get("ltp"))
    atm = perm.get("atm")
    walls = perm.get("walls") or {}
    ema200 = _f(cross.get("ema200") or cross.get("ema_slow"))
    vehicle = _choose_vehicle(side, spot, atm, perm.get("atm_iv"), atr, walls)
    buf = atr * 0.35 if atr else max(spot * 0.004, 1.0)

    if side == "BULLISH":
        stop_ma = ema200 - buf if ema200 else spot - buf * 2
        put_wall = walls.get("put_wall")
        stop = stop_ma
        stop_src = "below 200 EMA"
        if put_wall and float(put_wall) < spot:
            pw = float(put_wall) - buf * 0.25
            if pw > stop_ma * 0.5:
                # use the closer of 200 and put wall (tighter valid stop)
                if abs(spot - pw) < abs(spot - stop_ma):
                    stop, stop_src = pw, f"below put wall {put_wall}"
        t1 = walls.get("call_wall")
        t1_src = "call wall" if t1 else None
        if not t1:
            t1 = spot + max(buf * 4, spot * 0.008)
            t1_src = "1.5–2R proxy"
        invalid = "15m close back through 200, or 4H flips bearish"
    else:
        stop_ma = ema200 + buf if ema200 else spot + buf * 2
        call_wall = walls.get("call_wall")
        stop = stop_ma
        stop_src = "above 200 EMA"
        if call_wall and float(call_wall) > spot:
            cw = float(call_wall) + buf * 0.25
            if abs(cw - spot) < abs(stop_ma - spot):
                stop, stop_src = cw, f"above call wall {call_wall}"
        t1 = walls.get("put_wall")
        t1_src = "put wall" if t1 else None
        if not t1:
            t1 = spot - max(buf * 4, spot * 0.008)
            t1_src = "1.5–2R proxy"
        invalid = "15m close back through 200, or 4H flips bullish"

    risk = abs(spot - float(stop))
    reward = abs(float(t1) - spot) if t1 else None
    rr = (reward / risk) if risk and reward else None

    return {
        "side": "LONG" if side == "BULLISH" else "SHORT",
        "trigger": (
            f"7/200 {cross.get('fresh_label') or cross.get('bars_ago')} "
            f"first-cross vol {cross.get('volume_ratio')}×"
        ),
        "sponsor": (perm.get("hits") or [{}])[0].get("detail") if perm.get("hits") else None,
        "vehicle": vehicle,
        "entry": (
            "Next 15m hold above 200 / pullback to 7"
            if side == "BULLISH"
            else "Next 15m hold below 200 / pullback to 7"
        ),
        "stop": round(float(stop), 2),
        "stop_src": stop_src,
        "target1": round(float(t1), 2) if t1 else None,
        "target1_src": t1_src,
        "rr": round(rr, 2) if rr else None,
        "time_stop": "No follow-through by +4 closed 15m bars → flatten",
        "invalidation": invalid,
        "adx": adx,
        "vwap": round(vwap, 2) if vwap else None,
        "atr": round(atr, 2) if atr else None,
        "mtf_allowed": mtf.get("allowed_side"),
        "h4_bias": mtf.get("h4_bias"),
    }


def classify_board(
    *,
    kind: str,
    cross: Dict[str, Any],
    t_score: float,
    perm: Dict[str, Any],
    gate: Dict[str, Any],
    adx: Optional[float],
    extension: float,
) -> Tuple[str, str]:
    """
    Returns (board, reason).
    TRADE = permissioned ticket allowed.
    WATCH = near or fresh waiting / mixed 4H / bar-2 not strict enough.
    REJECT = hard fail.
    """
    p = float(perm.get("p") or 0)
    hard = list(perm.get("hard_fail") or [])
    bars = cross.get("bars_ago")
    bars_i = 99 if bars is None else int(bars)

    if gate.get("hard"):
        return "REJECT", gate.get("detail") or gate.get("reason") or "MTF hard gate"
    if "OC_CONFLICT" in hard or "FUTURES_OPPOSITE" in hard:
        return "REJECT", "; ".join(perm.get("miss") or hard)
    if kind == "NEAR":
        return "WATCH", "Approaching 200 — wait for close-through"

    if adx is not None and adx < ADX_TRADE_MIN:
        return "WATCH", f"ADX {adx:.1f} < {ADX_TRADE_MIN:.0f} — no trend"

    if bars_i == 2:
        if extension > BARS2_MAX_EXT_PCT or p < BARS2_MIN_P:
            return (
                "WATCH",
                f"bars_ago 2 needs ext≤{BARS2_MAX_EXT_PCT}% and P≥{BARS2_MIN_P:.0f} "
                f"(ext {extension:.2f}% P {p:.0f})",
            )

    if bars_i > 2:
        return "REJECT", f"stale bars_ago={bars_i}"

    if "NO_VEHICLE" in hard or "NO_CHAIN" in hard:
        return "WATCH" if p >= 30 else "REJECT", "No tradable ATM options / no chain"

    if p < P_AVOID:
        return "REJECT", f"Permission {p:.0f} < {P_AVOID:.0f}"

    a_ok = (
        t_score >= 70
        and p >= P_A
        and gate.get("reason") == "ALIGNED"
        and (perm.get("futures") or {}).get("state")
        in ("LONG_BUILDUP", "SHORT_BUILDUP")
    )
    setup_ok = t_score >= T_SETUP and p >= P_SETUP and not gate.get("soft")
    mixed_cap = bool(gate.get("soft"))

    if a_ok and not mixed_cap and bars_i <= 1:
        return "TRADE", "A-SETUP"
    if setup_ok and bars_i <= 1:
        return "TRADE", "SETUP"
    if bars_i == 2 and p >= BARS2_MIN_P and extension <= BARS2_MAX_EXT_PCT and t_score >= T_SETUP:
        if mixed_cap:
            return "WATCH", "4H mixed — bar-2 not promoted"
        return "TRADE", "SETUP (bar-2 strict)"
    if p >= P_AVOID:
        return "WATCH", f"Fresh but P {p:.0f} / T {t_score:.0f} not ticket-ready"
    return "REJECT", f"P {p:.0f}"


def enrich_candidate(
    symbol: str,
    *,
    candles: List[Dict[str, Any]],
    cross: Optional[Dict[str, Any]] = None,
    near: Optional[Dict[str, Any]] = None,
    fast_ma: int = 7,
    slow_ma: int = 200,
) -> Optional[Dict[str, Any]]:
    """Attach MTF gate, permission, ticket, board. Pure CPU."""
    from app.services import symbol_store as store

    kind = "FRESH" if cross else "NEAR"
    src = dict(cross or near or {})
    if not src:
        return None
    side = (src.get("cross_type") or "").upper()
    if side not in ("BULLISH", "BEARISH"):
        return None

    snap = store.get(symbol) or {}
    mtf = mtf_for_symbol(symbol)
    gate = mtf_gate(side, mtf)
    adx = compute_adx(candles)
    vwap = session_vwap(candles)
    atr = compute_atr(candles)
    ext = _f(src.get("extension_from_200_pct"))
    slope_ok = ema200_slope_aligned(candles, slow_ma, side)

    t_score = _f(src.get("momentum_score") or src.get("approach_score"))
    if kind == "FRESH":
        if adx is not None and adx < ADX_TRADE_MIN:
            t_score = min(t_score, 20.0)
        if not slope_ok:
            t_score = max(0.0, t_score - 12)

    perm = permission_from_snapshot(symbol, side, snap=snap, spot=_f(src.get("ltp")))
    board, board_reason = classify_board(
        kind=kind,
        cross=src,
        t_score=t_score,
        perm=perm,
        gate=gate,
        adx=adx,
        extension=ext,
    )

    # Hard MTF: never a LONG/SHORT ticket
    ticket = None
    grade = None
    if board == "TRADE" and not gate.get("hard"):
        ticket = build_ticket(
            symbol=symbol,
            cross_type=side,
            cross=src,
            perm=perm,
            mtf=mtf,
            adx=adx,
            vwap=vwap,
            atr=atr,
        )
        if not ticket:
            board, board_reason = "WATCH", "Permission ok but no vehicle"
        else:
            grade = "A-SETUP" if board_reason.startswith("A-") else "SETUP"

    if gate.get("hard"):
        board = "REJECT"
        ticket = None
        grade = None

    desk_score = round(0.45 * t_score + 0.55 * float(perm.get("p") or 0), 1)
    name = symbol.replace("NSE:", "").replace("-EQ", "").replace("-INDEX", "")
    spot = _f(perm.get("spot") or src.get("ltp") or (snap.get("spot") or {}).get("ltp"))

    return {
        "symbol": symbol,
        "name": name,
        "kind": kind,
        "ltp": spot,
        "cross_type": side,
        "cross_time": src.get("cross_time"),
        "volume_ratio": src.get("volume_ratio"),
        "volume_rising": src.get("volume_rising"),
        "trend_15m": src.get("trend_15m") or ("Up" if side == "BULLISH" else "Down"),
        "ema7": src.get("ema7"),
        "ema200": src.get("ema200"),
        "ema_fast": src.get("ema7"),
        "ema_slow": src.get("ema200"),
        "bars_ago": src.get("bars_ago"),
        "fresh_label": src.get("fresh_label") or ("NEAR" if kind == "NEAR" else None),
        "freshness": src.get("freshness") or kind,
        "first_cross_in_15d": src.get("first_cross_in_15d"),
        "crosses_in_15d": src.get("crosses_in_15d"),
        "extension_from_200_pct": ext,
        "momentum_score": src.get("momentum_score") or src.get("approach_score"),
        "approach_score": src.get("approach_score"),
        "body_strength": src.get("body_strength"),
        "gap_pct": src.get("gap_pct"),
        "adx": adx,
        "vwap": round(vwap, 2) if vwap else None,
        "ema200_slope_ok": slope_ok,
        "mtf_allowed": gate.get("allowed_side"),
        "h4_bias": gate.get("h4_bias") or mtf.get("h4_bias"),
        "mtf_gate": gate.get("reason"),
        "mtf_gate_hard": bool(gate.get("hard")),
        "permission": perm.get("p"),
        "permission_hits": perm.get("hits") or [],
        "permission_miss": perm.get("miss") or [],
        "hard_fail": perm.get("hard_fail") or [],
        "buildup_state": (perm.get("buildup") or {}).get("primary_state"),
        "buildup_note": (perm.get("buildup") or {}).get("note"),
        "futures_state": (perm.get("futures") or {}).get("state"),
        "oi_pcr": perm.get("oi_pcr"),
        "atm_iv": perm.get("atm_iv"),
        "put_wall": (perm.get("walls") or {}).get("put_wall"),
        "call_wall": (perm.get("walls") or {}).get("call_wall"),
        "desk_score": desk_score,
        "board": board,
        "board_reason": board_reason,
        "grade": grade,
        "ticket": ticket,
        "status": board,
    }


def evaluate_symbol(
    symbol: str,
    *,
    candles: List[Dict[str, Any]],
    cross_type: Optional[str] = None,
    fast_ma: int = 7,
    slow_ma: int = 200,
    window_days: int = 15,
    vol_mult: float = 1.5,
) -> Dict[str, Any]:
    """Analyze endpoint: detect + enrich from store candles."""
    from app.services.strategies.ma7200_scanner import detect_7_200_cross

    cross = detect_7_200_cross(
        candles,
        require_volume=True,
        skip_session_edge=True,
        vol_mult=vol_mult,
        first_cross_window_days=window_days,
        fast_period=fast_ma,
        slow_period=slow_ma,
        max_bars_ago=2,
    )
    if cross_type and cross and (cross.get("cross_type") or "").upper() != cross_type.upper():
        # honor caller side even if latest cross differs — still permission that side
        cross = dict(cross)
        cross["cross_type"] = cross_type.upper()
    near = None if cross else score_near_cross(candles, fast=fast_ma, slow=slow_ma)
    if cross_type and near and (near.get("cross_type") or "").upper() != cross_type.upper():
        near = dict(near)
        near["cross_type"] = cross_type.upper()
    row = enrich_candidate(
        symbol, candles=candles, cross=cross, near=near, fast_ma=fast_ma, slow_ma=slow_ma
    )
    if not row:
        return {"success": False, "error": "No 7/200 trigger or near-cross on stored 15m", "symbol": symbol}
    return {"success": True, **row}
