"""
Chain Anomaly Engine — the only Flow Radar decision brain.

Laws:
  • Analyse the whole chain, not one strike.
  • Structure (PCR / walls / pin / skew) is separate from flow (OI + premium).
  • Primary selector: high option volume + high OI change at support/resistance
    (put wall / call wall), compared to this chain and to past-day chain volume.
  • Futures / HTF are context. They do not hide a live wall-volume setup.
  • WAIT / QUIET is a valid output when the book is quiet or conflicted.
  • No LIS, no A+/desk_score, no RSI, no delivery dummy.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, time as dt_time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.services.option_analytics import (
    BUILDUP_LONG,
    BUILDUP_LU,
    BUILDUP_SC,
    BUILDUP_SHORT,
    _leg,
    analyze_chain_buildups,
    compute_atm_straddle,
    compute_greeks_walls,
    compute_iv_structure,
    compute_max_pain,
    compute_professional_pcr,
    compute_structure_walls,
)
from app.services.radar_signal_engine import (
    classify_signal,
    derive_oi_change_pct,
    compute_vor,
    compute_footstep_score,
)
from app.utils.market_hours import IST

GRADE_QUIET = "QUIET"
GRADE_WATCH = "WATCH"
GRADE_TRADEABLE = "TRADEABLE"

BIAS_BULL = "BULLISH"
BIAS_BEAR = "BEARISH"
BIAS_CONFLICT = "CONFLICTED"
BIAS_NEUTRAL = "NEUTRAL"
BIAS_PIN = "PIN"

BUCKET_INDEX = "INDEX"
BUCKET_HEAVY = "HEAVY"
BUCKET_REST = "REST"

INDEX_SYMBOLS = {
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    "NSE:FINNIFTY-INDEX",
}

# Combined CE+PE session volume — below this the print is junk.
LIQUIDITY_COMBINED = {
    BUCKET_INDEX: 100_000,
    BUCKET_HEAVY: 10_000,
    BUCKET_REST: 10_000,
}

# Absolute OI-add / volume floors for a strike to count as SIZE.
SIZE_FLOORS = {
    BUCKET_INDEX: (200_000, 50_000),
    BUCKET_HEAVY: (40_000, 8_000),
    BUCKET_REST: (15_000, 3_000),
}

# Present-session *chain* option volume to count as High Vol (not history, not vs own strikes).
HIGH_CHAIN_VOL = {
    BUCKET_INDEX: 800_000,
    BUCKET_HEAVY: 180_000,
    BUCKET_REST: 150_000,
}

MIN_OI_PCT = 8.0
OTM_LOC_LO = 2.0
OTM_LOC_HI = 6.0
FAR_OTM = 7.0
WALL_NEAR_PCT = 1.5
PIN_NEAR_PCT = 0.4
PIN_DTE = 3
VWAP_NEAR_PCT = 0.25
LOCATION_WALL_PCT = 0.45
MIN_RR = 1.0
ATR_STOP_MULT = 0.60
STRADDLE_CRUSH = -6.0
STRADDLE_EXPAND = 6.0
SKEW_EDGE = 2.0
CLUSTER_MIN = 3
VOL_SPIKE_OWN = 3.0
HIGH_STRIKE_VOL_X = 2.0
WALL_STEPS = 2
WALL_OI_PCT = 5.0
CHAIN_VOL_EXPAND_AVG = 2.0
CHAIN_VOL_EXPAND_PREV = 1.30
OR_HUNT_END = dt_time(14, 30)
UNIQUE_SCORE_FLOOR = 0.92
UNIQUE_TAG_CAP = 12
VOLUME_HISTORY_DAYS = 8
OR_BREAK_BUFFER_PCT = 0.05
CLEAN_ROOM_ATR = 0.45
PREMIUM_CONFIRM_PCT = 1.5
PERSIST_GRADES = {GRADE_WATCH, GRADE_TRADEABLE}
FADE_FUTURES = {"SHORT_COVERING", "LONG_UNWINDING"}
WRITING_BULL = {"Put Writing", "Call Long Unwinding"}
WRITING_BEAR = {"Call Writing", "Put Long Unwinding"}
BUYING_BULL = {"Fresh Call Buying"}
BUYING_BEAR = {"Fresh Put Buying"}
EXHAUSTION = {
    "Call Short Covering",
    "Put Short Covering",
    "Call Long Unwinding",
    "Put Long Unwinding",
}


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _name_of(symbol: str) -> str:
    part = (symbol or "").split(":")[-1]
    return part.replace("-EQ", "").replace("-INDEX", "") or symbol


def liquidity_bucket(symbol: str, heavy: Optional[Sequence[str]] = None) -> str:
    if symbol in INDEX_SYMBOLS or "-INDEX" in (symbol or ""):
        return BUCKET_INDEX
    if heavy is None:
        try:
            from app.services.fno_stocks import TOP_FNO_STOCKS

            heavy = TOP_FNO_STOCKS
        except Exception:
            heavy = []
    if symbol in set(heavy or []):
        return BUCKET_HEAVY
    return BUCKET_REST


def size_floors(bucket: str) -> Tuple[float, float]:
    return SIZE_FLOORS.get(bucket, SIZE_FLOORS[BUCKET_REST])


def combined_volume_floor(bucket: str) -> float:
    return float(LIQUIDITY_COMBINED.get(bucket, LIQUIDITY_COMBINED[BUCKET_REST]))


def nearest_atm(chain: Sequence[Dict[str, Any]], spot: float) -> Optional[float]:
    strikes = [
        _f(r.get("strike_price"))
        for r in chain
        if r.get("strike_price") is not None
    ]
    if not strikes or spot <= 0:
        return None
    return min(strikes, key=lambda s: abs(s - spot))


def strike_step(chain: Sequence[Dict[str, Any]]) -> float:
    strikes = sorted(
        {
            _f(r.get("strike_price"))
            for r in chain
            if r.get("strike_price") is not None
        }
    )
    gaps = [strikes[i + 1] - strikes[i] for i in range(len(strikes) - 1) if strikes[i + 1] > strikes[i]]
    return min(gaps) if gaps else 0.0


def parse_dte(expiries: Any, now: Optional[datetime] = None) -> Optional[int]:
    if not expiries:
        return None
    first = expiries[0] if isinstance(expiries, list) else expiries
    raw = first
    if isinstance(first, dict):
        raw = first.get("expiry") or first.get("date") or first.get("expiryDate") or first.get("expiry_date")
    if raw is None:
        return None
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = IST.localize(now)
    text = str(raw).strip()
    dt = None
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y", "%Y%m%d", "%d%b%Y"):
        try:
            dt = datetime.strptime(text[:11].replace("  ", " "), fmt)
            break
        except ValueError:
            continue
    if dt is None:
        try:
            ts = float(raw)
            if ts > 10_000_000_000:
                ts /= 1000.0
            dt = datetime.fromtimestamp(ts)
        except (TypeError, ValueError, OSError):
            return None
    if dt.tzinfo is None:
        try:
            dt = IST.localize(dt)
        except Exception:
            dt = dt.replace(tzinfo=now.tzinfo)
    return max(0, (dt.date() - now.date()).days)


def session_metrics(candles: Sequence[Dict[str, Any]], spot: float) -> Dict[str, Any]:
    """Real VWAP / EMA20 / ATR from stored 15m bars. Never invent VWAP=LTP."""
    bars = [c for c in candles or [] if _f(c.get("close") or c.get("ltp")) > 0]
    out = {
        "vwap": None,
        "ema20": None,
        "atr": None,
        "vwap_dev_pct": None,
        "above_ema20": None,
        "ok": False,
    }
    if not bars:
        return out
    num = den = 0.0
    closes: List[float] = []
    for c in bars:
        h, l, cl = _f(c.get("high")), _f(c.get("low")), _f(c.get("close") or c.get("ltp"))
        vol = _f(c.get("volume"))
        typical = (h + l + cl) / 3.0 if (h or l) else cl
        if vol > 0:
            num += typical * vol
            den += vol
        closes.append(cl)
    vwap = (num / den) if den > 0 else None
    ema20 = None
    if len(closes) >= 20:
        k = 2.0 / 21.0
        ema20 = sum(closes[:20]) / 20.0
        for px in closes[20:]:
            ema20 = px * k + ema20 * (1.0 - k)
    atr = None
    if len(bars) >= 5:
        trs: List[float] = []
        prev_c = _f(bars[0].get("close"))
        for c in bars[1:]:
            h, l, cl = _f(c.get("high")), _f(c.get("low")), _f(c.get("close"))
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            trs.append(tr)
            prev_c = cl
        window = trs[-14:] if len(trs) >= 14 else trs
        if window:
            atr = sum(window) / len(window)
    out["vwap"] = round(vwap, 4) if vwap else None
    out["ema20"] = round(ema20, 4) if ema20 else None
    out["atr"] = round(atr, 4) if atr else None
    if vwap and spot:
        out["vwap_dev_pct"] = round((spot - vwap) / vwap * 100.0, 3)
    if ema20 is not None and spot:
        out["above_ema20"] = bool(spot >= ema20)
    out["ok"] = bool(vwap or ema20 or atr)
    return out


def chain_volume_totals(chain: Sequence[Dict[str, Any]]) -> Tuple[float, float, float]:
    ce = pe = 0.0
    for row in chain or []:
        ce += _f((row.get("call") or {}).get("volume"))
        pe += _f((row.get("put") or {}).get("volume"))
    return ce, pe, ce + pe


def build_digest(
    chain: Sequence[Dict[str, Any]],
    structure: Dict[str, Any],
    prev_digest: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Compact previous-pass memory: walls, legs, rolling chain-volume days."""
    legs: Dict[str, Dict[str, float]] = {}
    for row in chain or []:
        strike = _f(row.get("strike_price"))
        if strike <= 0:
            continue
        for side, key in (("CE", "call"), ("PE", "put")):
            opt = row.get(key) or {}
            legs[f"{strike:g}:{side}"] = {
                "oi": _f(opt.get("oi")),
                "volume": _f(opt.get("volume")),
                "ltp": _f(opt.get("ltp")),
            }
    ce_vol, pe_vol, total_vol = chain_volume_totals(chain)
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        try:
            now = IST.localize(now)
        except Exception:
            pass
    today = now.date().isoformat()
    hist = list((prev_digest or {}).get("volume_history") or [])
    updated = False
    for row in hist:
        if row.get("date") == today:
            if total_vol >= _f(row.get("total")):
                row["total"] = total_vol
                row["ce"] = ce_vol
                row["pe"] = pe_vol
                row["ts"] = now.isoformat()
            updated = True
            break
    if not updated:
        hist.append({
            "date": today,
            "total": total_vol,
            "ce": ce_vol,
            "pe": pe_vol,
            "ts": now.isoformat(),
        })
    hist = hist[-VOLUME_HISTORY_DAYS:]
    straddle = structure.get("straddle") or {}
    cur_straddle = _f(straddle.get("straddle"))
    straddle_hist = list((prev_digest or {}).get("straddle_history") or [])
    if cur_straddle > 0:
        straddle_hist.append({"value": cur_straddle, "ts": now.isoformat()})
    straddle_hist = straddle_hist[-10:]

    cur_pcr = _f(structure.get("oi_pcr"), 1.0)
    pcr_hist = list((prev_digest or {}).get("pcr_history") or [])
    pcr_hist.append({"oi_pcr": cur_pcr, "ts": now.isoformat()})
    pcr_hist = pcr_hist[-10:]

    return {
        "call_wall": structure.get("call_wall"),
        "put_wall": structure.get("put_wall"),
        "oi_pcr": structure.get("oi_pcr"),
        "straddle": straddle.get("straddle"),
        "legs": legs,
        "total_volume": total_vol,
        "ce_volume": ce_vol,
        "pe_volume": pe_vol,
        "volume_history": hist,
        "harvest_ts": now.isoformat(),
        "straddle_history": straddle_hist,
        "pcr_history": pcr_hist,
    }


def compute_oi_velocity(
    current_oi: float,
    prev_leg_oi: Optional[float],
    current_ts: datetime,
    prev_ts_str: Optional[str],
) -> Tuple[float, bool]:
    """
    Returns (contracts_per_minute, is_positive_accumulation).
    Calculates the rate of open interest changes between harvest sweeps.
    """
    if prev_leg_oi is None or prev_leg_oi <= 0 or not prev_ts_str:
        return 0.0, False
    try:
        prev_dt = datetime.fromisoformat(prev_ts_str.replace("Z", "+00:00"))
        if prev_dt.tzinfo is None:
            prev_dt = IST.localize(prev_dt)
        if current_ts.tzinfo is None:
            current_ts = IST.localize(current_ts)
        delta_sec = max(10.0, (current_ts - prev_dt).total_seconds())
    except Exception:
        delta_sec = 180.0
    delta_oi = float(current_oi or 0) - float(prev_leg_oi or 0)
    minutes = delta_sec / 60.0
    contracts_per_min = delta_oi / minutes
    return round(contracts_per_min, 1), delta_oi > 0


def detect_squeeze_active(
    futures: Dict[str, Any],
    flow_bias: str,
    anomalies: Sequence[Dict[str, Any]],
    chain: Sequence[Dict[str, Any]],
    spot: float,
) -> Tuple[bool, Optional[str]]:
    """
    Short Squeeze Detection:
    Condition:
      1. Futures show SHORT_COVERING (trapped bears forced to cover).
      2. Flow bias is BULLISH (genuine call buying / put writing).
      3. Call option flow shows aggressive fresh buying with positive premium change and VOR >= 0.4.
    When this happens, it is NOT a fade. It is an explosive short squeeze setup!
    """
    fut_state = str(futures.get("state") or "").upper()
    if fut_state != "SHORT_COVERING":
        return False, None
    if flow_bias != BIAS_BULL:
        return False, None

    ce_buying = any(
        a.get("side") == "CE"
        and a.get("label") == "Fresh Call Buying"
        and not a.get("exhaustion")
        and (_f(a.get("vor")) >= 0.4 or abs(_f(a.get("oi_added"))) >= 20000 or _f(a.get("vol_x")) >= 1.8)
        for a in anomalies
    )
    if ce_buying:
        return True, "Short squeeze active: Futures short covering + aggressive Call buying"
    return False, None


def straddle_compression_state(
    straddle_hist: List[Dict[str, Any]],
    current_straddle: float,
) -> str:
    """Detects COMPRESSED (coiled spring) vs EXPLODING (breakout in progress)."""
    if len(straddle_hist) < 3 or current_straddle <= 0:
        return "NORMAL"
    early_avg = sum(_f(h.get("value")) for h in straddle_hist[:3]) / 3.0
    if early_avg <= 0:
        return "NORMAL"
    if current_straddle < early_avg * 0.85:
        return "COMPRESSED"
    if current_straddle > early_avg * 1.12:
        prev_val = _f(straddle_hist[-2].get("value")) if len(straddle_hist) >= 2 else early_avg
        if current_straddle > prev_val:
            return "EXPLODING"
    return "NORMAL"


def pcr_velocity_signal(pcr_hist: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Measures the rate of change of PCR across consecutive harvests."""
    if len(pcr_hist) < 2:
        return {"signal": "STABLE", "delta": 0.0, "bias": BIAS_NEUTRAL}
    cur = _f(pcr_hist[-1].get("oi_pcr"), 1.0)
    prev = _f(pcr_hist[-2].get("oi_pcr"), 1.0)
    delta = round(cur - prev, 3)
    if delta <= -0.12:
        return {"signal": "PCR_COLLAPSING", "delta": delta, "bias": BIAS_BEAR}
    if delta >= 0.12:
        return {"signal": "PCR_SURGING", "delta": delta, "bias": BIAS_BULL}
    return {"signal": "STABLE", "delta": delta, "bias": BIAS_NEUTRAL}


def chain_volume_regime(
    chain: Sequence[Dict[str, Any]],
    prev_digest: Optional[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Current chain option volume vs last harvest and vs past-day average."""
    ce_vol, pe_vol, total = chain_volume_totals(chain)
    prev = prev_digest or {}
    now = now or datetime.now(IST)
    today = (now.date().isoformat() if hasattr(now, "date") else None)
    hist = list(prev.get("volume_history") or [])
    prior_days = [
        _f(h.get("total"))
        for h in hist
        if _f(h.get("total")) > 0 and h.get("date") != today
    ]
    avg_days = (sum(prior_days) / len(prior_days)) if prior_days else None
    prev_total = _f(prev.get("total_volume"))
    # Same-day previous harvest still useful as an intraday pace check.
    vs_avg = (total / avg_days) if avg_days and avg_days > 0 else None
    vs_prev = (total / prev_total) if prev_total > 0 else None
    expanded = bool(
        (vs_avg is not None and vs_avg >= CHAIN_VOL_EXPAND_AVG)
        or (vs_prev is not None and vs_avg is None and vs_prev >= CHAIN_VOL_EXPAND_PREV)
        or (vs_avg is not None and vs_avg >= CHAIN_VOL_EXPAND_AVG)
    )
    hottest = None
    hottest_vol = 0.0
    leg_vols: List[float] = []
    for row in chain or []:
        strike = _f(row.get("strike_price"))
        for side, key in (("CE", "call"), ("PE", "put")):
            vol = _f((row.get(key) or {}).get("volume"))
            if vol > 0:
                leg_vols.append(vol)
            if vol > hottest_vol:
                hottest_vol = vol
                hottest = {"strike": strike, "side": side, "volume": vol}
    median_leg = 0.0
    if leg_vols:
        s = sorted(leg_vols)
        n = len(s)
        mid = n // 2
        median_leg = float(s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0)
    hottest_vol_x = (hottest_vol / median_leg) if median_leg > 0 and hottest_vol > 0 else None
    if hottest and hottest_vol_x:
        hottest = {**hottest, "vol_x": round(hottest_vol_x, 2)}
    return {
        "ce_volume": ce_vol,
        "pe_volume": pe_vol,
        "total_volume": total,
        "avg_past_days": round(avg_days, 0) if avg_days else None,
        "past_days_n": len(prior_days),
        "prev_harvest_volume": prev_total or None,
        "vs_avg": round(vs_avg, 2) if vs_avg else None,
        "vs_prev": round(vs_prev, 2) if vs_prev else None,
        "expanded": expanded,
        "hottest": hottest,
        "median_leg_volume": round(median_leg, 0) if median_leg else None,
        "hottest_vol_x": round(hottest_vol_x, 2) if hottest_vol_x else None,
    }


def _candle_dt(c: Dict[str, Any]) -> Optional[datetime]:
    raw = c.get("datetime") or c.get("timestamp")
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=IST).replace(tzinfo=None)
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(IST).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def opening_range_from_candles(
    candles: Sequence[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """First 15 minutes from stored intraday candles; falls back to last session."""
    now = now or datetime.now(IST).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(IST).replace(tzinfo=None)
    by_date: Dict[Any, List[Dict[str, Any]]] = {}
    for c in candles or []:
        dt = _candle_dt(c)
        if dt is None:
            continue
        if dt_time(9, 15) <= dt.time() < dt_time(9, 30):
            by_date.setdefault(dt.date(), []).append(c)
    if not by_date:
        return {"orh": None, "orl": None, "valid": False, "bars": 0, "session_date": None}
    today = now.date()
    session = today if today in by_date else max(by_date)
    bars = by_date[session]
    orh = max(_f(c.get("high")) for c in bars)
    orl = min(_f(c.get("low")) for c in bars)
    session_open_done = datetime.combine(session, dt_time(9, 30))
    naive_now = now.replace(tzinfo=None) if getattr(now, "tzinfo", None) else now
    return {
        "orh": round(orh, 2),
        "orl": round(orl, 2),
        "valid": naive_now >= session_open_done,
        "bars": len(bars),
        "mid": round((orh + orl) / 2.0, 2),
        "session_date": session.isoformat(),
    }


def _nearest_level(
    spot: float,
    levels: Sequence[Tuple[str, Any]],
    direction: str,
) -> Tuple[Optional[str], Optional[float], Optional[float]]:
    usable = []
    for name, raw in levels:
        px = _f(raw)
        if px <= 0:
            continue
        if direction == BIAS_BULL and px > spot:
            usable.append((px - spot, name, px))
        elif direction == BIAS_BEAR and px < spot:
            usable.append((spot - px, name, px))
    if not usable:
        return None, None, None
    dist, name, px = min(usable, key=lambda x: x[0])
    return name, round(px, 2), round(dist, 2)


def breakout_room(
    *,
    spot: float,
    direction: str,
    structure: Dict[str, Any],
    session: Dict[str, Any],
    atr: Optional[float],
    extra_levels: Optional[Sequence[Tuple[str, Any]]] = None,
) -> Dict[str, Any]:
    """Room before the next institutional wall/OR/max-pain level."""
    if spot <= 0:
        return {"clean": False, "reason": "No spot"}
    atr_f = _f(atr) if atr else max(spot * 0.006, 1.0)
    levels = [
        ("ORH", session.get("orh")),
        ("ORL", session.get("orl")),
        ("CALL_WALL", structure.get("call_wall")),
        ("PUT_WALL", structure.get("put_wall")),
        ("GAMMA_WALL", structure.get("gamma_wall")),
        ("MAX_PAIN", structure.get("max_pain")),
    ]
    if extra_levels:
        levels.extend(list(extra_levels))
    name, px, dist = _nearest_level(spot, levels, direction)
    if px is None or dist is None:
        return {"clean": True, "next_level": None, "distance": None, "distance_atr": None}
    dist_atr = dist / max(atr_f, 1e-9)
    clean = dist_atr >= CLEAN_ROOM_ATR
    return {
        "clean": bool(clean),
        "next_level": name,
        "level": px,
        "distance": dist,
        "distance_atr": round(dist_atr, 2),
        "reason": None if clean else f"{name} too close",
    }


def _best_fuel(
    anomalies: Sequence[Dict[str, Any]],
    direction: str,
) -> Optional[Dict[str, Any]]:
    side = "CE" if direction == BIAS_BULL else "PE" if direction == BIAS_BEAR else None
    if not side:
        return None
    rows = [
        a for a in anomalies
        if a.get("side") == side
        and a.get("direction") == direction
        and not a.get("exhaustion")
        and _f(a.get("ltp_chg_pct")) >= PREMIUM_CONFIRM_PCT
        and (_f(a.get("oi_added")) > 0 or _f(a.get("oi_change_pct")) >= MIN_OI_PCT)
    ]
    for a in rows:
        a["premium_spent"] = round(_f(a.get("volume")) * _f(a.get("ltp")), 0)
    rows.sort(
        key=lambda a: (
            -_f(a.get("premium_spent")),
            -_f(a.get("oi_added")),
            -_f(a.get("volume")),
            _f(a.get("atm_dist_pct"), 99),
        )
    )
    return rows[0] if rows else None


def _day_map_levels(day_map: Optional[Dict[str, Any]]) -> List[Tuple[str, Any]]:
    day = day_map or {}
    cam = day.get("camarilla") or {}
    classic = day.get("classic") or day.get("pivots") or {}
    return [
        ("PDH", day.get("pdh")),
        ("PDL", day.get("pdl")),
        ("CAM_R3", cam.get("r3") or cam.get("R3")),
        ("CAM_S3", cam.get("s3") or cam.get("S3")),
        ("R1", classic.get("r1") or classic.get("R1")),
        ("S1", classic.get("s1") or classic.get("S1")),
        ("P", classic.get("p") or classic.get("P") or day.get("pivot")),
    ]


def opening_range_signal(
    *,
    spot: float,
    candles: Sequence[Dict[str, Any]],
    anomalies: Sequence[Dict[str, Any]],
    structure: Dict[str, Any],
    atr: Optional[float],
    now: Optional[datetime] = None,
    extra_levels: Optional[Sequence[Tuple[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Opening-range breakout with OI, premium, volume, and clean-room checks."""
    session = opening_range_from_candles(candles, now=now)
    session["vwap"] = None
    if not session.get("valid") or spot <= 0:
        return [], {**session, "break_state": "WAIT_OR"}
    orh = _f(session.get("orh"))
    orl = _f(session.get("orl"))
    buf = max(spot * OR_BREAK_BUFFER_PCT / 100.0, 0.01)
    direction = None
    if orh and spot >= orh + buf:
        direction = BIAS_BULL
    elif orl and spot <= orl - buf:
        direction = BIAS_BEAR
    if not direction:
        return [], {**session, "break_state": "INSIDE_OR"}

    fuel = _best_fuel(anomalies, direction)
    room = breakout_room(
        spot=spot,
        direction=direction,
        structure=structure,
        session=session,
        atr=atr,
        extra_levels=extra_levels,
    )
    naive_now = now
    if naive_now is None:
        naive_now = datetime.now(IST).replace(tzinfo=None)
    elif getattr(naive_now, "tzinfo", None) is not None:
        naive_now = naive_now.astimezone(IST).replace(tzinfo=None)
    try:
        from datetime import date as _date
        raw_sd = session.get("session_date")
        session_date = _date.fromisoformat(str(raw_sd)) if raw_sd else naive_now.date()
    except Exception:
        session_date = naive_now.date()
    t = naive_now.time()
    in_manage = session_date == naive_now.date() and OR_HUNT_END <= t <= dt_time(15, 30)
    confirmed = bool(fuel and room.get("clean") and not in_manage)
    label = "ORH breakout confirmed" if direction == BIAS_BULL else "ORL breakdown confirmed"
    reason = None
    if in_manage:
        reason = "No new OR break after 14:30"
    elif not fuel:
        reason = "Needs OI + premium confirmation"
    elif not room.get("clean"):
        reason = room.get("reason") or "No clean room"
    out = {
        **session,
        "break_state": "OR_BREAK_LONG" if direction == BIAS_BULL else "OR_BREAK_SHORT",
        "confirmed": confirmed,
        "room": room,
        "reason": reason,
        "fuel": {
            "strike": (fuel or {}).get("strike"),
            "oi_added": (fuel or {}).get("oi_added"),
            "ltp_chg_pct": (fuel or {}).get("ltp_chg_pct"),
            "premium_spent": (fuel or {}).get("premium_spent"),
        } if fuel else None,
    }
    if not confirmed:
        return [], out
    return [
        {
            "type": out["break_state"],
            "types": [out["break_state"], "OPENING_RANGE", "PREMIUM_EXPANSION", "SIZE"],
            "side": fuel.get("side"),
            "strike": fuel.get("strike"),
            "oi": fuel.get("oi"),
            "oi_added": fuel.get("oi_added"),
            "oi_change_pct": fuel.get("oi_change_pct"),
            "volume": fuel.get("volume"),
            "vol_x": fuel.get("vol_x"),
            "vor": fuel.get("vor"),
            "oi_velocity": fuel.get("oi_velocity"),
            "ltp": fuel.get("ltp"),
            "ltp_chg_pct": fuel.get("ltp_chg_pct"),
            "delta": fuel.get("delta"),
            "label": label,
            "signal": "OR_BREAKOUT",
            "direction": direction,
            "exhaustion": False,
            "atm_dist_pct": fuel.get("atm_dist_pct"),
            "location": "OPENING_RANGE",
            "clean_room": room,
            "premium_spent": fuel.get("premium_spent"),
        }
    ], out


def wall_activity(
    chain: Sequence[Dict[str, Any]],
    spot: float,
    structure: Dict[str, Any],
    bucket: str,
    prev_digest: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """High option volume + high OI change sitting on support (put wall) or resistance (call wall)."""
    oi_floor, vol_floor = size_floors(bucket)
    step = strike_step(chain)
    put_wall = structure.get("put_wall")
    call_wall = structure.get("call_wall")
    prev_legs = (prev_digest or {}).get("legs") or {}
    all_vols = []
    for row in chain or []:
        all_vols.append(_f((row.get("call") or {}).get("volume")))
        all_vols.append(_f((row.get("put") or {}).get("volume")))
    flags: List[Dict[str, Any]] = []

    def _near(strike: float, wall: Any) -> bool:
        if not wall or strike <= 0:
            return False
        if step > 0:
            return abs(strike - _f(wall)) <= step * WALL_STEPS + 0.01
        if not spot:
            return False
        return abs(strike - _f(wall)) / spot * 100.0 <= 1.2

    def _scan(wall: Any, kind: str, default_side: str) -> Optional[Dict[str, Any]]:
        if not wall:
            return None
        members: List[Dict[str, Any]] = []
        for row in chain or []:
            strike = _f(row.get("strike_price"))
            if not _near(strike, wall):
                continue
            for side, key in (("CE", "call"), ("PE", "put")):
                opt = row.get(key) or {}
                vol = _f(opt.get("volume"))
                oi = _f(opt.get("oi"))
                if vol <= 0 and oi <= 0:
                    continue
                prev_leg = prev_legs.get(f"{strike:g}:{side}")
                added = _oi_added(opt, prev_leg)
                oi_pct = derive_oi_change_pct(opt)
                if abs(oi_pct) < 0.01 and oi > 0 and added:
                    prev_oi = oi - added
                    if prev_oi > 0:
                        oi_pct = added / prev_oi * 100.0
                peer = _peer_median(all_vols, vol)
                vol_x = (vol / peer) if peer > 0 else None
                members.append({
                    "strike": strike,
                    "side": side,
                    "opt": opt,
                    "volume": vol,
                    "oi": oi,
                    "oi_added": added,
                    "oi_change_pct": oi_pct,
                    "vol_x": vol_x,
                    "ltp_chg_pct": _f(opt.get("chg_pct") or opt.get("chp")),
                    "delta": opt.get("delta"),
                    "ltp": _f(opt.get("ltp")),
                })
        if not members:
            return None
        tot_vol = sum(m["volume"] for m in members)
        tot_oi = sum(abs(m["oi_added"]) for m in members)
        hottest = max(members, key=lambda m: (m["volume"], abs(m["oi_added"])))
        outside = [
            _f((row.get(key) or {}).get("volume"))
            for row in chain or []
            for key in ("call", "put")
            if not _near(_f(row.get("strike_price")), wall)
        ]
        peer = _peer_median(outside, 0.0)
        vol_x = (hottest["volume"] / peer) if peer > 0 else hottest.get("vol_x")
        hottest["vol_x"] = vol_x
        vol_ok = hottest["volume"] >= vol_floor * 2.0 or (
            vol_x is not None and vol_x >= HIGH_STRIKE_VOL_X
        )
        oi_ok = (
            hottest["oi_added"] > 0
            and (
                abs(hottest["oi_change_pct"]) >= WALL_OI_PCT
                or abs(hottest["oi_added"]) >= oi_floor * 0.5
            )
        )
        if not (vol_ok and oi_ok and tot_vol >= vol_floor):
            return None
        sig = classify_signal(
            hottest["oi_change_pct"], hottest["ltp_chg_pct"], 0.0, opt_type=hottest["side"]
        )
        direction = sig.get("direction") or BIAS_NEUTRAL
        label = sig.get("label") or ""
        if direction not in (BIAS_BULL, BIAS_BEAR):
            writing = hottest["oi_added"] > 0 and hottest["ltp_chg_pct"] <= 0
            if kind == "SUPPORT":
                direction = BIAS_BULL if writing else BIAS_BEAR
            else:
                direction = BIAS_BEAR if writing else BIAS_BULL
        wall_vor = compute_vor(tot_vol, hottest["oi"])
        return {
            "type": "WALL_SUPPORT" if kind == "SUPPORT" else "WALL_RESISTANCE",
            "types": ["WALL_SUPPORT" if kind == "SUPPORT" else "WALL_RESISTANCE", "SIZE"],
            "wall": _f(wall),
            "kind": kind,
            "side": hottest["side"] or default_side,
            "strike": hottest["strike"],
            "oi": hottest["oi"],
            "oi_added": round(tot_oi, 0),
            "oi_change_pct": round(hottest["oi_change_pct"], 2),
            "volume": tot_vol,
            "vol_x": round(hottest["vol_x"], 2) if hottest.get("vol_x") else None,
            "vor": wall_vor,
            "ltp": hottest["ltp"],
            "ltp_chg_pct": round(hottest["ltp_chg_pct"], 2),
            "delta": hottest.get("delta"),
            "label": label or ("Support flow" if kind == "SUPPORT" else "Resistance flow"),
            "signal": sig.get("signal"),
            "direction": direction,
            "exhaustion": label in EXHAUSTION,
            "atm_dist_pct": round(abs(hottest["strike"] - spot) / spot * 100.0, 2) if spot else None,
            "location": kind,
        }

    sup = _scan(put_wall, "SUPPORT", "PE")
    res = _scan(call_wall, "RESISTANCE", "CE")
    if sup:
        flags.append(sup)
    if res:
        flags.append(res)
    return flags


def _oi_added(opt: Dict[str, Any], prev_leg: Optional[Dict[str, Any]]) -> float:
    """Session OI added (vs yesterday / prev_oi). Last-harvest OI is for volume spike only."""
    prev = opt.get("prev_oi")
    if prev is not None and _f(prev) > 0:
        return _f(opt.get("oi")) - _f(prev)
    chg = _f(opt.get("oi_change") or opt.get("oich"))
    if chg:
        return chg
    pct = derive_oi_change_pct(opt)
    oi = _f(opt.get("oi"))
    if oi and abs(pct) >= 0.01 and pct > -99.9:
        prev_est = oi / (1.0 + pct / 100.0)
        return oi - prev_est
    if prev_leg and _f(prev_leg.get("oi")) > 0:
        return _f(opt.get("oi")) - _f(prev_leg.get("oi"))
    return 0.0


def _own_vol_x(volume: float, prev_leg: Optional[Dict[str, Any]]) -> Optional[float]:
    if not prev_leg:
        return None
    base = _f(prev_leg.get("volume"))
    if base <= 0:
        return None
    return volume / base


def structure_layer(
    chain: Sequence[Dict[str, Any]],
    spot: float,
    atm: Optional[float],
    dte: Optional[int],
) -> Dict[str, Any]:
    pcr = compute_professional_pcr(list(chain), spot=spot, atm=atm, band=5)
    walls = compute_structure_walls(list(chain), spot)
    greeks = compute_greeks_walls(list(chain), spot)
    pain = compute_max_pain(list(chain))
    if spot and pain.get("max_pain"):
        pain["distance_from_spot"] = round(_f(pain["max_pain"]) - spot, 2)
        pain["distance_pct"] = round((_f(pain["max_pain"]) - spot) / spot * 100.0, 3)
    iv = compute_iv_structure(list(chain), spot, atm)
    straddle = compute_atm_straddle(list(chain), spot, atm)
    buildup = analyze_chain_buildups(list(chain), spot, atm, band=3)

    oi_pcr = _f(pcr.get("oi_pcr"), 1.0)
    vol_pcr = _f(pcr.get("volume_pcr"), 1.0)
    call_wall = walls.get("call_wall")
    put_wall = walls.get("put_wall")
    gamma_wall = greeks.get("gamma_wall_strike")
    pin_risk = _f(greeks.get("pin_risk"))
    dist_g = greeks.get("distance_to_gamma_wall_pct")
    skew = _f(iv.get("skew"))
    skew_edge = abs(skew) >= SKEW_EDGE

    pin = False
    if (
        gamma_wall
        and spot
        and dist_g is not None
        and _f(dist_g) < PIN_NEAR_PCT
        and (dte is None or dte <= PIN_DTE)
        and pin_risk >= 35
    ):
        pin = True

    def _near(wall: Any) -> bool:
        if not wall or not spot:
            return False
        return abs(_f(wall) - spot) / spot * 100.0 <= WALL_NEAR_PCT

    def _dominant(wall_oi: float, series: Sequence[float]) -> bool:
        vals = [x for x in series if x > 0]
        if not vals or wall_oi <= 0:
            return False
        med = sorted(vals)[len(vals) // 2]
        return wall_oi >= max(med * 1.6, 1.0)

    put_ois = [_f((row.get("put") or {}).get("oi")) for row in chain or []]
    call_ois = [_f((row.get("call") or {}).get("oi")) for row in chain or []]
    put_wall_oi = _f(walls.get("put_wall_oi"))
    call_wall_oi = _f(walls.get("call_wall_oi"))
    near_put = _near(put_wall)
    near_call = _near(call_wall)
    put_wall_dominant = _dominant(put_wall_oi, put_ois)
    call_wall_dominant = _dominant(call_wall_oi, call_ois)

    if pin:
        structure_bias = BIAS_PIN
    elif oi_pcr < 0.70 and _near(call_wall):
        structure_bias = BIAS_BEAR
    elif oi_pcr > 1.25 and _near(put_wall):
        structure_bias = BIAS_BULL
    elif oi_pcr < 0.70:
        structure_bias = BIAS_BEAR
    elif oi_pcr > 1.25:
        structure_bias = BIAS_BULL
    elif pcr.get("oi_bias") in (BIAS_BULL, BIAS_BEAR) and pcr.get("regime") not in (
        "BALANCED",
        "PUT_LEAN",
        "CALL_LEAN",
    ):
        structure_bias = str(pcr.get("oi_bias"))
    else:
        structure_bias = BIAS_NEUTRAL

    atm_pack = buildup.get("atm") or {}
    # atm may be a dict of call/put states or nested
    atm_ce = (
        (atm_pack.get("call") or {}).get("state")
        if isinstance(atm_pack, dict)
        else None
    ) or buildup.get("primary_state")
    atm_pe = (atm_pack.get("put") or {}).get("state") if isinstance(atm_pack, dict) else None

    band = buildup.get("atm_band") or []
    if band:
        mid = next((r for r in band if r.get("is_atm")), band[len(band) // 2])
        atm_ce = (mid.get("call") or {}).get("state") or atm_ce
        atm_pe = (mid.get("put") or {}).get("state") or atm_pe

    return {
        "oi_pcr": round(oi_pcr, 3),
        "vol_pcr": round(vol_pcr, 3),
        "atm_pcr": pcr.get("atm_oi_pcr"),
        "regime": pcr.get("regime"),
        "regime_label": pcr.get("regime_label"),
        "call_wall": call_wall,
        "put_wall": put_wall,
        "call_wall_oi": walls.get("call_wall_oi"),
        "put_wall_oi": walls.get("put_wall_oi"),
        "near_put_wall": bool(near_put),
        "near_call_wall": bool(near_call),
        "put_wall_dominant": bool(put_wall_dominant),
        "call_wall_dominant": bool(call_wall_dominant),
        "gamma_wall": gamma_wall,
        "pin_risk": pin_risk,
        "pin": pin,
        "max_pain": pain.get("max_pain"),
        "max_pain_dist_pct": pain.get("distance_pct"),
        "iv_skew": round(skew, 2),
        "skew_label": iv.get("skew_label"),
        "skew_edge": bool(skew_edge),
        "straddle": straddle,
        "atm_ce_state": atm_ce,
        "atm_pe_state": atm_pe,
        "buildup_primary": buildup.get("primary_state"),
        "buildup_bias": buildup.get("bias"),
        "structure_bias": structure_bias,
        "delta_bias": greeks.get("delta_bias"),
        "pcr": pcr,
        "walls": walls,
        "greeks": greeks,
        "iv": iv,
        "buildup": {
            "primary_state": buildup.get("primary_state"),
            "bias": buildup.get("bias"),
            "conviction": buildup.get("conviction"),
            "note": buildup.get("note"),
            "strong_long_ce": buildup.get("strong_long_ce"),
            "strong_long_pe": buildup.get("strong_long_pe"),
            "strong_short_ce": buildup.get("strong_short_ce"),
            "strong_short_pe": buildup.get("strong_short_pe"),
        },
    }


def futures_layer(futures: Optional[Dict[str, Any]], spot: float) -> Dict[str, Any]:
    fut = dict(futures or {})
    ok = bool(fut.get("ok") and _f(fut.get("ltp")) > 0)
    state = str(fut.get("state") or "UNKNOWN").upper()
    direction = str(fut.get("direction") or BIAS_NEUTRAL).upper()
    ltp = _f(fut.get("ltp")) if ok else None
    basis = None
    if ok and spot and ltp:
        basis = round(ltp - spot, 2)
    fade = state in FADE_FUTURES
    if not ok or state in ("UNKNOWN", "CHURN", ""):
        fut_bias = BIAS_NEUTRAL
    elif state == "LONG_BUILDUP":
        fut_bias = BIAS_BULL
    elif state == "SHORT_BUILDUP":
        fut_bias = BIAS_BEAR
    else:
        # covering / unwinding / trapped — not a trade generator
        fut_bias = BIAS_NEUTRAL
    return {
        "ok": ok,
        "ltp": ltp,
        "basis": basis,
        "state": state if ok else "MISSING",
        "direction": direction if ok else BIAS_NEUTRAL,
        "oi": fut.get("oi"),
        "oi_change": fut.get("oi_change") or fut.get("oi_chg"),
        "oi_change_pct": fut.get("oi_change_pct"),
        "change_pct": fut.get("change_pct") or fut.get("price_change_pct"),
        "label": fut.get("label"),
        "fade": fade,
        "futures_bias": fut_bias,
        "missing": not ok,
    }


def _peer_median(volumes: List[float], self_vol: float) -> float:
    peers = [v for v in volumes if v > 0]
    # Exclude self once if present so a busy contract is not compared to itself.
    if self_vol > 0 and peers:
        try:
            peers.remove(self_vol)
        except ValueError:
            pass
    if len(peers) >= 3:
        s = sorted(peers)
        n = len(s)
        mid = n // 2
        return (s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0)
    if peers:
        return sum(peers) / len(peers)
    return 0.0


def strike_anomalies(
    chain: Sequence[Dict[str, Any]],
    spot: float,
    atm: Optional[float],
    bucket: str,
    prev_digest: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    oi_floor, vol_floor = size_floors(bucket)
    prev_legs = (prev_digest or {}).get("legs") or {}
    step = strike_step(chain)
    ce_vols = [
        _f((r.get("call") or {}).get("volume"))
        for r in chain
        if r.get("call")
    ]
    pe_vols = [
        _f((r.get("put") or {}).get("volume"))
        for r in chain
        if r.get("put")
    ]

    flags: List[Dict[str, Any]] = []
    for row in chain:
        strike = _f(row.get("strike_price"))
        if strike <= 0 or spot <= 0:
            continue
        atm_dist = abs(strike - spot) / spot * 100.0
        if atm_dist > 12.0:
            continue
        for side, key, peers in (("CE", "call", ce_vols), ("PE", "put", pe_vols)):
            opt = row.get(key) or {}
            oi = _f(opt.get("oi"))
            vol = _f(opt.get("volume"))
            if oi <= 0 and vol <= 0:
                continue
            prev_leg = prev_legs.get(f"{strike:g}:{side}")
            added = _oi_added(opt, prev_leg)
            oi_pct = derive_oi_change_pct(opt)
            if abs(oi_pct) < 0.01 and oi > 0 and added:
                prev_oi = oi - added
                if prev_oi > 0:
                    oi_pct = added / prev_oi * 100.0
            ltp_chg = _f(opt.get("chg_pct") or opt.get("chp"))
            own_x = _own_vol_x(vol, prev_leg)
            peer_med = _peer_median(peers, vol)
            peer_x = (vol / peer_med) if peer_med > 0 else None
            vol_x = own_x if own_x is not None else peer_x
            vol_src = "own_snapshot" if own_x is not None else "peer_median"

            vor = compute_vor(vol, oi)
            now_dt = datetime.now(IST)
            prev_ts = (prev_digest or {}).get("harvest_ts")
            oi_vel, is_accel = compute_oi_velocity(oi, prev_leg.get("oi") if prev_leg else None, now_dt, prev_ts)

            size_hit = (
                abs(added) >= oi_floor
                and abs(oi_pct) >= MIN_OI_PCT
                and vol >= vol_floor
            )
            high_vol = (
                vol_x is not None
                and vol_x >= HIGH_STRIKE_VOL_X
                and (abs(oi_pct) >= WALL_OI_PCT or abs(added) >= oi_floor * 0.35)
                and vol >= vol_floor * 0.6
            )
            vor_hit = (
                vor >= 0.65
                and vol >= vol_floor * 0.4
                and (abs(added) >= oi_floor * 0.25 or abs(oi_pct) >= 12.0)
            )
            footstep_early = (
                (vor >= 0.5 or abs(oi_vel) >= 500.0)
                and atm_dist <= 3.5
                and abs(added) >= oi_floor * 0.3
                and ((side == "CE" and ltp_chg > 0) or (side == "PE" and ltp_chg > 0))
            )
            if not size_hit and not high_vol and not vor_hit and not footstep_early:
                continue

            sig = classify_signal(oi_pct, ltp_chg, 0.0, opt_type=side)
            label = sig.get("label") or "Neutral/Inconclusive"
            direction = sig.get("direction") or BIAS_NEUTRAL

            loc = "ATM"
            if OTM_LOC_LO <= atm_dist <= OTM_LOC_HI:
                loc = "OTM"
            elif atm_dist > FAR_OTM:
                loc = "FAR_OTM"
            elif atm_dist < 1.0:
                loc = "ATM"

            types: List[str] = []
            if footstep_early:
                types.append("FOOTSTEP_EARLY")
            if vor_hit:
                types.append("VOR_SHOCK")
            if size_hit:
                types.append("SIZE")
            if high_vol and "HIGH_STRIKE_VOL" not in types:
                types.append("HIGH_STRIKE_VOL")
            if not types:
                types.append("SIZE")

            if loc == "OTM":
                types.append("OTM_SIZE")
            elif loc == "FAR_OTM":
                types.append("FAR_OTM_SIZE")
            if vol_x is not None and vol_x >= VOL_SPIKE_OWN:
                types.append("VOL_SPIKE")

            flags.append({
                "type": types[0],
                "types": types,
                "side": side,
                "strike": strike,
                "oi": oi,
                "oi_added": round(added, 0),
                "oi_change_pct": round(oi_pct, 2),
                "volume": vol,
                "vol_x": round(vol_x, 2) if vol_x is not None else None,
                "vol_src": vol_src,
                "vor": vor,
                "oi_velocity": oi_vel,
                "is_accelerating": is_accel,
                "ltp": _f(opt.get("ltp")),
                "ltp_chg_pct": round(ltp_chg, 2),
                "iv": _f(opt.get("iv")) or None,
                "delta": opt.get("delta"),
                "atm_dist_pct": round(atm_dist, 2),
                "location": loc,
                "label": label,
                "signal": sig.get("signal"),
                "direction": direction,
                "exhaustion": label in EXHAUSTION,
                "step": step,
            })

    # Cluster: ≥3 adjacent strikes, same side, same direction, each a size flag.
    if step > 0:
        for side in ("CE", "PE"):
            by_dir: Dict[str, List[Dict[str, Any]]] = {}
            for a in flags:
                if a["side"] != side or a["exhaustion"]:
                    continue
                by_dir.setdefault(a["direction"], []).append(a)
            for direction, group in by_dir.items():
                if direction not in (BIAS_BULL, BIAS_BEAR):
                    continue
                group = sorted(group, key=lambda x: x["strike"])
                run: List[Dict[str, Any]] = []
                for a in group:
                    if not run or abs(a["strike"] - run[-1]["strike"]) <= step * 1.01:
                        run.append(a)
                    else:
                        if len(run) >= CLUSTER_MIN:
                            _mark_cluster(flags, run)
                        run = [a]
                if len(run) >= CLUSTER_MIN:
                    _mark_cluster(flags, run)

    return flags


def _mark_cluster(flags: List[Dict[str, Any]], run: List[Dict[str, Any]]) -> None:
    strikes = {r["strike"] for r in run}
    center = run[len(run) // 2]
    flags.append({
        "type": "CLUSTER",
        "types": ["CLUSTER"],
        "side": center["side"],
        "strike": center["strike"],
        "oi_added": sum(r["oi_added"] for r in run),
        "volume": sum(r["volume"] for r in run),
        "label": center["label"],
        "direction": center["direction"],
        "signal": center.get("signal"),
        "exhaustion": False,
        "cluster_strikes": sorted(strikes),
        "cluster_n": len(run),
        "atm_dist_pct": center.get("atm_dist_pct"),
        "location": "CLUSTER",
    })
    for a in flags:
        if a.get("strike") in strikes and a.get("side") == center["side"] and a.get("type") != "CLUSTER":
            types = list(a.get("types") or [])
            if "CLUSTER_MEMBER" not in types:
                types.append("CLUSTER_MEMBER")
            a["types"] = types


def wall_and_straddle_flags(
    structure: Dict[str, Any],
    prev_digest: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    prev = prev_digest or {}
    if (
        prev.get("call_wall") is not None
        and structure.get("call_wall") is not None
        and _f(prev["call_wall"]) != _f(structure["call_wall"])
    ):
        out.append({
            "type": "WALL_SHIFT",
            "side": "CE",
            "strike": structure["call_wall"],
            "from_strike": prev.get("call_wall"),
            "label": "Call wall migrated",
            "direction": BIAS_BEAR if _f(structure["call_wall"]) > _f(prev["call_wall"]) else BIAS_BULL,
            "exhaustion": False,
        })
    if (
        prev.get("put_wall") is not None
        and structure.get("put_wall") is not None
        and _f(prev["put_wall"]) != _f(structure["put_wall"])
    ):
        out.append({
            "type": "WALL_SHIFT",
            "side": "PE",
            "strike": structure["put_wall"],
            "from_strike": prev.get("put_wall"),
            "label": "Put wall migrated",
            "direction": BIAS_BULL if _f(structure["put_wall"]) < _f(prev["put_wall"]) else BIAS_BEAR,
            "exhaustion": False,
        })
    cur_st = _f((structure.get("straddle") or {}).get("straddle"))
    prev_st = _f(prev.get("straddle"))
    if cur_st > 0 and prev_st > 0:
        chg = (cur_st - prev_st) / prev_st * 100.0
        if chg <= STRADDLE_CRUSH:
            out.append({
                "type": "STRADDLE_CRUSH",
                "value": round(chg, 1),
                "label": f"ATM straddle {chg:.1f}% (crush / writing)",
                "direction": BIAS_NEUTRAL,
                "exhaustion": False,
            })
        elif chg >= STRADDLE_EXPAND:
            out.append({
                "type": "STRADDLE_EXPAND",
                "value": round(chg, 1),
                "label": f"ATM straddle {chg:.1f}% (premium expansion)",
                "direction": BIAS_NEUTRAL,
                "exhaustion": False,
            })
    return out


def flow_bias_from_anomalies(
    anomalies: Sequence[Dict[str, Any]],
    structure_bias: str = BIAS_NEUTRAL,
) -> Tuple[str, float, float, bool]:
    """Net flow from anomalous strikes.

    Writing at the *opposing* wall of a structural ceiling/floor is defensive,
    not a side flip. Put writing under a call-writing ceiling does not make
    the book bullish; call writing under a put-writing floor does not make it
    bearish.
    """
    bull = bear = 0.0
    exhaustion_only = True
    any_fuel = False
    for a in anomalies:
        if a.get("type") in ("STRADDLE_CRUSH", "STRADDLE_EXPAND", "WALL_SHIFT", "CHAIN_VOL_EXPAND"):
            # wall shift votes weakly in its tagged direction
            if a.get("type") == "WALL_SHIFT":
                w = 0.75
                if a.get("direction") == BIAS_BULL:
                    bull += w
                elif a.get("direction") == BIAS_BEAR:
                    bear += w
            continue
        label = a.get("label") or ""
        w = 2.0 if a.get("type") in ("CLUSTER", "OTM_SIZE", "WALL_SUPPORT", "WALL_RESISTANCE") else 1.0
        if a.get("cluster_n"):
            w = max(w, 2.0)
        if label in EXHAUSTION:
            continue
        exhaustion_only = False
        any_fuel = True
        defensive = (
            (structure_bias == BIAS_BEAR and label in WRITING_BULL)
            or (structure_bias == BIAS_BULL and label in WRITING_BEAR)
        )
        if defensive:
            # Size is real; it does not vote against the ceiling/floor.
            continue
        if label in BUYING_BULL or label in WRITING_BULL:
            bull += w
        elif label in BUYING_BEAR or label in WRITING_BEAR:
            bear += w
        elif a.get("direction") == BIAS_BULL:
            bull += 0.5 * w
        elif a.get("direction") == BIAS_BEAR:
            bear += 0.5 * w
    if not any_fuel:
        return BIAS_NEUTRAL, bull, bear, True
    if bull - bear >= 1.0:
        return BIAS_BULL, bull, bear, False
    if bear - bull >= 1.0:
        return BIAS_BEAR, bull, bear, False
    if bull > 0 and bear > 0:
        return BIAS_CONFLICT, bull, bear, False
    return BIAS_NEUTRAL, bull, bear, exhaustion_only


def _htf_gate(htf: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    htf = htf or {}
    daily = str(
        htf.get("daily_bias")
        or (htf.get("daily") or {}).get("bias")
        or htf.get("daily")
        or BIAS_NEUTRAL
    ).upper()
    h4 = str(
        htf.get("h4_bias")
        or (htf.get("h4") or {}).get("bias")
        or htf.get("h4")
        or BIAS_NEUTRAL
    ).upper()
    allowed = str(htf.get("allowed_side") or "NONE").upper()
    if allowed in ("LONG", BIAS_BULL):
        gate = "ALLOW_LONG"
    elif allowed in ("SHORT", BIAS_BEAR):
        gate = "ALLOW_SHORT"
    else:
        # Infer from 4H if fuse didn't run.
        if h4 == BIAS_BULL and daily != BIAS_BEAR:
            gate = "ALLOW_LONG"
        elif h4 == BIAS_BEAR and daily != BIAS_BULL:
            gate = "ALLOW_SHORT"
        else:
            gate = "NONE"
    opposite = None
    if gate == "ALLOW_LONG":
        opposite = BIAS_BEAR
    elif gate == "ALLOW_SHORT":
        opposite = BIAS_BULL
    return {
        "daily": daily if daily in (BIAS_BULL, BIAS_BEAR, "MIXED", BIAS_NEUTRAL) else BIAS_NEUTRAL,
        "h4": h4 if h4 in (BIAS_BULL, BIAS_BEAR, "MIXED", BIAS_NEUTRAL) else BIAS_NEUTRAL,
        "allowed_side": allowed,
        "gate": gate,
        "blocks": opposite,
        "ok": bool(htf.get("ok") or h4 in (BIAS_BULL, BIAS_BEAR) or daily in (BIAS_BULL, BIAS_BEAR)),
    }


def agree_bias(a: str, b: str) -> bool:
    return a in (BIAS_BULL, BIAS_BEAR) and a == b


def decide_grade(
    *,
    structure_bias: str,
    futures: Dict[str, Any],
    flow_bias: str,
    htf: Dict[str, Any],
    anomalies: Sequence[Dict[str, Any]],
    exhaustion_only: bool,
    index_ctx: Optional[Dict[str, Any]],
    prev_report: Optional[Dict[str, Any]],
    snapshot_pass: Optional[str] = None,
    volume_regime: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str, str, List[str]]:
    """
    Returns (grade, chain_bias, snapshot_intent, why_not_parts).

    Wall + high option volume at support/resistance is the primary selector.
    It does not wait for a second harvest or for futures.
    """
    why: List[str] = []
    fut_bias = futures.get("futures_bias") or BIAS_NEUTRAL
    fut_missing = bool(futures.get("missing"))
    fade = bool(futures.get("fade"))
    vol = volume_regime or {}

    if structure_bias == BIAS_PIN:
        return GRADE_WATCH, BIAS_CONFLICT, GRADE_WATCH, [
            "Gamma wall pinning spot — no directional card"
        ]

    walls = [
        a
        for a in anomalies
        if a.get("type") in ("WALL_SUPPORT", "WALL_RESISTANCE") and not a.get("exhaustion")
    ]
    if walls:
        sup = [a for a in walls if a.get("type") == "WALL_SUPPORT"]
        res = [a for a in walls if a.get("type") == "WALL_RESISTANCE"]
        wall_bias = BIAS_NEUTRAL
        note = ""
        if sup and not res:
            wall_bias = str(sup[0].get("direction") or BIAS_BULL)
            note = (
                f"High OI+vol at support {sup[0].get('strike')} "
                f"ΔOI {sup[0].get('oi_added')} vol {sup[0].get('volume')}"
            )
        elif res and not sup:
            wall_bias = str(res[0].get("direction") or BIAS_BEAR)
            note = (
                f"High OI+vol at resistance {res[0].get('strike')} "
                f"ΔOI {res[0].get('oi_added')} vol {res[0].get('volume')}"
            )
        else:
            s0, r0 = sup[0], res[0]
            s_score = abs(_f(s0.get("oi_added"))) * max(_f(s0.get("volume")), 1)
            r_score = abs(_f(r0.get("oi_added"))) * max(_f(r0.get("volume")), 1)
            if s_score >= r_score * 1.35:
                wall_bias = str(s0.get("direction") or BIAS_BULL)
                note = f"Support flow dominates resistance ({s0.get('strike')})"
            elif r_score >= s_score * 1.35:
                wall_bias = str(r0.get("direction") or BIAS_BEAR)
                note = f"Resistance flow dominates support ({r0.get('strike')})"
            else:
                return GRADE_WATCH, BIAS_CONFLICT, GRADE_WATCH, [
                    "Support and resistance both hot with similar size — WAIT"
                ]
        if wall_bias in (BIAS_BULL, BIAS_BEAR):
            if (
                flow_bias in (BIAS_BULL, BIAS_BEAR)
                and structure_bias in (BIAS_BULL, BIAS_BEAR)
                and flow_bias != structure_bias
                and flow_bias != wall_bias
            ):
                return GRADE_WATCH, BIAS_CONFLICT, GRADE_WATCH, [
                    f"Wall {wall_bias} but flow {flow_bias} vs structure {structure_bias}"
                ]
            why.append(note)
            if vol.get("expanded") and vol.get("vs_avg"):
                why.append(f"Chain option volume {vol['vs_avg']}× past {vol.get('past_days_n')}d avg")
            elif vol.get("vs_avg"):
                why.append(f"Chain option volume {vol['vs_avg']}× past-day avg")
            return GRADE_TRADEABLE, wall_bias, GRADE_TRADEABLE, why

    votes = [v for v in (structure_bias, flow_bias, fut_bias) if v in (BIAS_BULL, BIAS_BEAR)]
    conflict = (
        flow_bias in (BIAS_BULL, BIAS_BEAR)
        and structure_bias in (BIAS_BULL, BIAS_BEAR)
        and flow_bias != structure_bias
    )
    if conflict:
        why.append(
            f"Flow {flow_bias} vs structure {structure_bias} — WAIT, never BUY the flow"
        )
        return GRADE_WATCH, BIAS_CONFLICT, GRADE_WATCH, why

    # Majority of the three.
    chain_bias = BIAS_NEUTRAL
    if votes:
        bull_n = sum(1 for v in votes if v == BIAS_BULL)
        bear_n = sum(1 for v in votes if v == BIAS_BEAR)
        if bull_n > bear_n and bull_n >= 2:
            chain_bias = BIAS_BULL
        elif bear_n > bull_n and bear_n >= 2:
            chain_bias = BIAS_BEAR
        elif bull_n == 1 and bear_n == 0 and flow_bias == BIAS_BULL and structure_bias in (BIAS_BULL, BIAS_NEUTRAL):
            chain_bias = BIAS_BULL
        elif bear_n == 1 and bull_n == 0 and flow_bias == BIAS_BEAR and structure_bias in (BIAS_BEAR, BIAS_NEUTRAL):
            chain_bias = BIAS_BEAR
        elif bull_n and bear_n:
            return GRADE_WATCH, BIAS_CONFLICT, GRADE_WATCH, [
                f"Split votes structure={structure_bias} flow={flow_bias} futures={fut_bias}"
            ]

    real = [
        a
        for a in anomalies
        if a.get("type") in (
            "OR_BREAK_LONG",
            "OR_BREAK_SHORT",
            "CLUSTER",
            "OTM_SIZE",
            "WALL_SHIFT",
            "SIZE",
            "VOL_SPIKE",
            "WALL_SUPPORT",
            "WALL_RESISTANCE",
            "HIGH_STRIKE_VOL",
        )
        and not a.get("exhaustion")
    ]
    has_strong = any(
        a.get("type") in (
            "OR_BREAK_LONG",
            "OR_BREAK_SHORT",
            "CLUSTER",
            "OTM_SIZE",
            "WALL_SHIFT",
            "WALL_SUPPORT",
            "WALL_RESISTANCE",
        )
        for a in real
    )
    has_any = bool(real) or any(
        a.get("type") in ("STRADDLE_CRUSH", "STRADDLE_EXPAND") for a in anomalies
    )

    if chain_bias not in (BIAS_BULL, BIAS_BEAR):
        if vol.get("expanded") or has_any:
            return GRADE_WATCH, BIAS_NEUTRAL if not votes else BIAS_CONFLICT, GRADE_WATCH, [
                "Volume/OI unusual but no single side yet"
            ]
        return GRADE_QUIET, BIAS_NEUTRAL, GRADE_QUIET, ["No unusual size, walls quiet, no volume expansion"]

    if exhaustion_only:
        why.append("Only exhaustion (covering / unwinding) — not a process trade")
        return GRADE_WATCH, chain_bias, GRADE_WATCH, why

    is_squeeze, squeeze_note = detect_squeeze_active(futures, flow_bias, anomalies, [], 0.0)
    if is_squeeze:
        fade = False
        if squeeze_note:
            why.append(squeeze_note)

    if fade:
        why.append(f"Futures {futures.get('state')} is fade-risk — cap WATCH")
        return GRADE_WATCH, chain_bias, GRADE_WATCH, why

    has_footstep_early = any(
        "FOOTSTEP_EARLY" in (a.get("types") or []) or a.get("type") == "FOOTSTEP_EARLY"
        for a in anomalies
    )

    if fut_missing and not has_strong and not vol.get("expanded") and not is_squeeze and not has_footstep_early:
        why.append("Futures book missing — cap WATCH until futures OI is in")
        return GRADE_WATCH, chain_bias, GRADE_WATCH, why

    # Need at least two of {structure, flow, futures} on the same side, or a high-urgency squeeze/footstep
    aligned = sum(
        1
        for v in (structure_bias, flow_bias, fut_bias)
        if v == chain_bias
    )
    if aligned < 2 and not is_squeeze and not has_footstep_early:
        why.append(
            f"Only {aligned}/3 layers on {chain_bias} (structure {structure_bias}, "
            f"flow {flow_bias}, futures {fut_bias})"
        )
        return GRADE_WATCH, chain_bias, GRADE_WATCH, why

    if not has_any and not is_squeeze and not has_footstep_early:
        why.append("Agreement without a size/wall anomaly — not institutional")
        return GRADE_WATCH, chain_bias, GRADE_WATCH, why

    # HTF opposite caps at WATCH — never flip the side to the MA.
    blocks = htf.get("blocks")
    if blocks and blocks == chain_bias and htf.get("ok"):
        why.append(f"HTF gate {htf.get('gate')} blocks {chain_bias}")
        return GRADE_WATCH, chain_bias, GRADE_WATCH, why

    idx_bias = str((index_ctx or {}).get("bias") or "").upper()
    if (
        index_ctx
        and idx_bias in (BIAS_BULL, BIAS_BEAR)
        and idx_bias != chain_bias
        and (index_ctx.get("grade") in (GRADE_TRADEABLE, GRADE_WATCH))
    ):
        why.append(f"Index {idx_bias} vs stock {chain_bias} — downgrade")
        return GRADE_WATCH, chain_bias, GRADE_WATCH, why

    intent = GRADE_TRADEABLE if (
        has_strong or vol.get("expanded") or is_squeeze or has_footstep_early or (aligned == 3 and has_any)
    ) else GRADE_WATCH
    if intent != GRADE_TRADEABLE:
        why.append("Agreement is soft (no wall/volume expansion)")
        return GRADE_WATCH, chain_bias, GRADE_WATCH, why

    # Wall / volume-expansion / short squeeze / footstep early setups print on this harvest.
    # Other 3-layer process trades still need the bias to repeat.
    if has_strong or vol.get("expanded") or is_squeeze or has_footstep_early:
        if has_footstep_early and not any("Early institutional footstep" in w for w in why):
            why.append("Early institutional footstep detected — momentum priority")
        return GRADE_TRADEABLE, chain_bias, GRADE_TRADEABLE, why

    # Persistence: same bias on the previous harvest.
    prev = prev_report or {}
    prev_bias = str(prev.get("chain_bias") or "")
    prev_intent = str(prev.get("snapshot_intent") or prev.get("grade") or "")
    cur_pass = snapshot_pass
    prev_pass = prev.get("pass_id")
    same_pass = bool(cur_pass and prev_pass and cur_pass == prev_pass)
    persisted = (
        prev_bias == chain_bias
        and prev_intent in (GRADE_TRADEABLE, GRADE_WATCH)
        and bool(prev)
        and not same_pass
    )
    if not persisted:
        why.append("Needs one more harvest with the same bias before a card")
        return GRADE_WATCH, chain_bias, GRADE_TRADEABLE, why

    return GRADE_TRADEABLE, chain_bias, GRADE_TRADEABLE, []


def _pick_instrument(
    chain_bias: str,
    anomalies: Sequence[Dict[str, Any]],
    atm: Optional[float],
    spot: float,
) -> Tuple[Optional[float], Optional[str], Optional[Dict[str, Any]]]:
    side = "CE" if chain_bias == BIAS_BULL else "PE" if chain_bias == BIAS_BEAR else None
    if not side:
        return None, None, None
    ranked = [
        a
        for a in anomalies
        if a.get("side") == side
        and not a.get("exhaustion")
        and a.get("type") in (
            "OR_BREAK_LONG",
            "OR_BREAK_SHORT",
            "CLUSTER",
            "OTM_SIZE",
            "SIZE",
            "VOL_SPIKE",
            "WALL_SUPPORT",
            "WALL_RESISTANCE",
            "HIGH_STRIKE_VOL",
        )
        and _f(a.get("atm_dist_pct"), 99) <= 5.5
    ]
    ranked.sort(
        key=lambda a: (
            0 if a.get("type") in ("OR_BREAK_LONG", "OR_BREAK_SHORT") else 1 if a.get("type") in ("WALL_SUPPORT", "WALL_RESISTANCE", "CLUSTER") else 2 if a.get("type") == "OTM_SIZE" else 3,
            -_f(a.get("oi_added")),
            _f(a.get("atm_dist_pct"), 99),
        )
    )
    if ranked:
        best = ranked[0]
        return _f(best.get("strike")), side, best
    if atm:
        return _f(atm), side, None
    return None, side, None


def _at_location(
    chain_bias: str,
    spot: float,
    vwap: Optional[float],
    put_wall: Any,
    call_wall: Any,
) -> Tuple[bool, str]:
    if vwap and spot:
        dev = abs(spot - vwap) / vwap * 100.0
        if chain_bias == BIAS_BULL and spot >= vwap and dev <= VWAP_NEAR_PCT * 4:
            return True, f"VWAP reclaim {vwap:.2f}"
        if chain_bias == BIAS_BEAR and spot <= vwap and dev <= VWAP_NEAR_PCT * 4:
            return True, f"VWAP reject {vwap:.2f}"
        if dev <= VWAP_NEAR_PCT:
            return True, f"At VWAP {vwap:.2f}"
    if chain_bias == BIAS_BULL and put_wall and spot:
        if abs(spot - _f(put_wall)) / spot * 100.0 <= LOCATION_WALL_PCT:
            return True, f"Put wall {put_wall}"
    if chain_bias == BIAS_BEAR and call_wall and spot:
        if abs(spot - _f(call_wall)) / spot * 100.0 <= LOCATION_WALL_PCT:
            return True, f"Call wall {call_wall}"
    return False, "Spot mid-range — no VWAP/wall location"


def build_trade_card(
    *,
    grade: str,
    chain_bias: str,
    snapshot_intent: str,
    anomalies: Sequence[Dict[str, Any]],
    structure: Dict[str, Any],
    spot: float,
    atm: Optional[float],
    vwap: Optional[float],
    atr: Optional[float],
    why: List[str],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    if snapshot_intent != GRADE_TRADEABLE and grade != GRADE_TRADEABLE:
        return None, why
    if chain_bias not in (BIAS_BULL, BIAS_BEAR):
        why = why + ["No directional bias for a card"]
        return None, why

    located, loc_label = _at_location(
        chain_bias, spot, vwap, structure.get("put_wall"), structure.get("call_wall")
    )
    if not located:
        wall_a = next(
            (
                a
                for a in anomalies
                if a.get("type") in ("WALL_SUPPORT", "WALL_RESISTANCE")
                and not a.get("exhaustion")
            ),
            None,
        )
        if wall_a:
            located = True
            kind = "support" if wall_a.get("type") == "WALL_SUPPORT" else "resistance"
            loc_label = f"{kind} {wall_a.get('strike')}"
        else:
            why = why + [loc_label]
            return None, why

    strike, opt, src = _pick_instrument(chain_bias, anomalies, atm, spot)
    if not strike or not opt:
        why = why + ["No strike in-direction with size"]
        return None, why

    delta = _f((src or {}).get("delta")) if src else 0.0
    if src and src.get("delta") is not None and abs(delta) < 0.15 and opt == (
        "CE" if chain_bias == BIAS_BULL else "PE"
    ):
        why = why + [f"Delta {delta:.2f} too low for a directional buy"]
        return None, why

    put_wall = _f(structure.get("put_wall")) if structure.get("put_wall") else None
    call_wall = _f(structure.get("call_wall")) if structure.get("call_wall") else None
    atr_stop = (atr * ATR_STOP_MULT) if atr and atr > 0 else spot * 0.006

    if chain_bias == BIAS_BULL:
        stop_wall = put_wall if put_wall and put_wall < spot else None
        stop = min(spot - atr_stop, stop_wall) if stop_wall else spot - atr_stop
        target = call_wall if call_wall and call_wall > spot else spot + max(atr_stop * 1.5, spot * 0.008)
        if structure.get("max_pain") and _f(structure["max_pain"]) > spot:
            target = min(target, _f(structure["max_pain"])) if call_wall else _f(structure["max_pain"])
        side = "LONG"
        action = "BUY CE"
    else:
        stop_wall = call_wall if call_wall and call_wall > spot else None
        stop = max(spot + atr_stop, stop_wall) if stop_wall else spot + atr_stop
        target = put_wall if put_wall and put_wall < spot else spot - max(atr_stop * 1.5, spot * 0.008)
        if structure.get("max_pain") and _f(structure["max_pain"]) < spot:
            target = max(target, _f(structure["max_pain"])) if put_wall else _f(structure["max_pain"])
        side = "SHORT"
        action = "BUY PE"

    risk = abs(spot - stop)
    reward = abs(target - spot)
    if risk <= 0 or reward / risk < MIN_RR:
        why = why + [f"R:R {reward / max(risk, 1e-9):.2f} < {MIN_RR} — no card"]
        return None, why

    inv = (
        f"Break {'put wall' if chain_bias == BIAS_BULL else 'call wall'} "
        f"{stop:.2f} or flow flips"
    )
    thesis_bits = [
        f"Structure {structure.get('regime')}",
        loc_label,
        (src or {}).get("label") or f"{opt} {strike:g}",
    ]
    card = {
        "side": side,
        "action": action,
        "instrument": opt,
        "strike": strike,
        "entry": round(spot, 2),
        "entry_label": loc_label,
        "stop": round(stop, 2),
        "target": round(target, 2),
        "rr": round(reward / risk, 2),
        "invalidation": inv,
        "thesis": " · ".join(str(x) for x in thesis_bits if x),
        "anomaly": (src or {}).get("type"),
    }
    if grade != GRADE_TRADEABLE:
        # Intent is tradeable but persistence/location already applied;
        # still no live card until grade says so.
        return None, why
    return card, why


def analyze_chain(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pure entry. `snapshot` keys:

      symbol, name?, chain, spot, atm?, expiry/expiries/dte?,
      futures?, prev_digest?, prev_report?,
      htf?, candles_15?, vwap?, ema20?, atr?,
      index_ctx?, vix?, heavy_symbols?, now?
    """
    symbol = snapshot.get("symbol") or ""
    name = snapshot.get("name") or _name_of(symbol)
    chain = list(snapshot.get("chain") or [])
    spot = _f(snapshot.get("spot"))
    bucket = liquidity_bucket(symbol, snapshot.get("heavy_symbols"))
    now = snapshot.get("now")
    ts = (now or datetime.now(IST)).isoformat()

    def _quiet(why: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        body = {
            "symbol": symbol,
            "name": name,
            "ts": ts,
            "spot": spot or None,
            "grade": GRADE_QUIET,
            "chain_bias": BIAS_NEUTRAL,
            "snapshot_intent": GRADE_QUIET,
            "anomalies": [],
            "trade": None,
            "why_not": why,
            "bucket": bucket,
            "structure": extra.get("structure") if extra else None,
            "futures": extra.get("futures") if extra else {"ok": False, "state": "MISSING", "missing": True},
            "htf": extra.get("htf") if extra else {},
            "digest": extra.get("digest") if extra else {"legs": {}},
        }
        if extra:
            for k, v in extra.items():
                if k not in body:
                    body[k] = v
        body["max_oi_added"] = _max_session_delta_oi(chain)
        body["setup_score"] = 0
        body["flags"] = screen_flags(body)
        return body

    if len(chain) < 6 or spot <= 0:
        return _quiet("Chain print unusable (rows < 6 or no spot)")

    total_vol = 0.0
    for row in chain:
        total_vol += _f((row.get("call") or {}).get("volume"))
        total_vol += _f((row.get("put") or {}).get("volume"))
    if total_vol < combined_volume_floor(bucket):
        return _quiet(
            f"Illiquid print ({total_vol:.0f} combined volume, floor {combined_volume_floor(bucket):.0f})"
        )

    atm = snapshot.get("atm") or nearest_atm(chain, spot)
    dte = snapshot.get("dte")
    if dte is None:
        dte = parse_dte(snapshot.get("expiries") or snapshot.get("expiry"), now if isinstance(now, datetime) else None)

    metrics = session_metrics(snapshot.get("candles_15") or [], spot)
    vwap = snapshot.get("vwap") if snapshot.get("vwap") is not None else metrics.get("vwap")
    ema20 = snapshot.get("ema20") if snapshot.get("ema20") is not None else metrics.get("ema20")
    atr = snapshot.get("atr") if snapshot.get("atr") is not None else metrics.get("atr")

    structure = structure_layer(chain, spot, atm, dte)
    futures = futures_layer(snapshot.get("futures"), spot)
    htf = _htf_gate(snapshot.get("htf"))
    prev_digest = snapshot.get("prev_digest") or {}
    vol_regime = chain_volume_regime(chain, prev_digest, now if isinstance(now, datetime) else None)
    anomalies = strike_anomalies(chain, spot, atm, bucket, prev_digest)
    anomalies.extend(wall_activity(chain, spot, structure, bucket, prev_digest))
    anomalies.extend(wall_and_straddle_flags(structure, prev_digest))
    or_anoms, or_session = opening_range_signal(
        spot=spot,
        candles=snapshot.get("candles_15") or [],
        anomalies=anomalies,
        structure=structure,
        atr=_f(atr) if atr else None,
        now=now if isinstance(now, datetime) else None,
        extra_levels=_day_map_levels(snapshot.get("day_map") or snapshot.get("levels")),
    )
    anomalies.extend(or_anoms)
    if vol_regime.get("expanded"):
        anomalies.append({
            "type": "CHAIN_VOL_EXPAND",
            "label": (
                f"Chain option volume {vol_regime.get('vs_avg')}× "
                f"{vol_regime.get('past_days_n')}d avg"
                if vol_regime.get("vs_avg")
                else f"Chain option volume {vol_regime.get('vs_prev')}× last harvest"
            ),
            "value": vol_regime.get("vs_avg") or vol_regime.get("vs_prev"),
            "direction": BIAS_NEUTRAL,
            "exhaustion": False,
        })

    flow_bias, bull_pts, bear_pts, exhaustion_only = flow_bias_from_anomalies(
        anomalies, structure["structure_bias"]
    )
    grade, chain_bias, intent, why = decide_grade(
        structure_bias=structure["structure_bias"],
        futures=futures,
        flow_bias=flow_bias,
        htf=htf,
        anomalies=anomalies,
        exhaustion_only=exhaustion_only,
        index_ctx=snapshot.get("index_ctx"),
        prev_report=snapshot.get("prev_report"),
        snapshot_pass=snapshot.get("pass_id"),
        volume_regime=vol_regime,
    )

    trade, why = build_trade_card(
        grade=grade,
        chain_bias=chain_bias,
        snapshot_intent=intent,
        anomalies=anomalies,
        structure=structure,
        spot=spot,
        atm=atm,
        vwap=_f(vwap) if vwap else None,
        atr=_f(atr) if atr else None,
        why=why,
    )
    if intent == GRADE_TRADEABLE and grade == GRADE_TRADEABLE and trade is None:
        grade = GRADE_WATCH

    digest = build_digest(
        chain,
        structure,
        prev_digest,
        now if isinstance(now, datetime) else None,
    )
    why_not = " · ".join(why) if why else (
        None if trade else ("Quiet book" if grade == GRADE_QUIET else "Watch — no card")
    )

    if grade != GRADE_QUIET and not anomalies:
        # Law: non-quiet must carry at least one flag. Tag structure regime.
        anomalies.append({
            "type": "STRUCTURE",
            "label": structure.get("regime_label") or structure.get("regime"),
            "direction": structure.get("structure_bias"),
            "exhaustion": False,
        })

    top = None
    for a in anomalies:
        if a.get("type") in (
            "OR_BREAK_LONG",
            "OR_BREAK_SHORT",
            "WALL_SUPPORT",
            "WALL_RESISTANCE",
            "CLUSTER",
            "OTM_SIZE",
            "WALL_SHIFT",
            "HIGH_STRIKE_VOL",
            "SIZE",
        ):
            top = a
            break
    if top is None and anomalies:
        top = anomalies[0]

    body = {
        "symbol": symbol,
        "name": name,
        "ts": ts,
        "spot": round(spot, 2),
        "atm": atm,
        "dte": dte,
        "bucket": bucket,
        "grade": grade,
        "chain_bias": chain_bias,
        "snapshot_intent": intent,
        "flow_bias": flow_bias,
        "flow_points": {"bull": round(bull_pts, 2), "bear": round(bear_pts, 2)},
        "structure": {
            "oi_pcr": structure["oi_pcr"],
            "vol_pcr": structure["vol_pcr"],
            "atm_pcr": structure.get("atm_pcr"),
            "regime": structure["regime"],
            "regime_label": structure["regime_label"],
            "call_wall": structure["call_wall"],
            "put_wall": structure["put_wall"],
            "call_wall_oi": structure.get("call_wall_oi"),
            "put_wall_oi": structure.get("put_wall_oi"),
            "near_put_wall": structure.get("near_put_wall"),
            "near_call_wall": structure.get("near_call_wall"),
            "put_wall_dominant": structure.get("put_wall_dominant"),
            "call_wall_dominant": structure.get("call_wall_dominant"),
            "gamma_wall": structure["gamma_wall"],
            "pin_risk": structure["pin_risk"],
            "pin": structure["pin"],
            "max_pain": structure["max_pain"],
            "iv_skew": structure["iv_skew"],
            "skew_label": structure["skew_label"],
            "skew_edge": structure["skew_edge"],
            "straddle": structure["straddle"],
            "straddle_chg_pct": (
                next((a.get("value") for a in anomalies if a.get("type") in ("STRADDLE_CRUSH", "STRADDLE_EXPAND")), None)
            ),
            "atm_ce_state": structure["atm_ce_state"],
            "atm_pe_state": structure["atm_pe_state"],
            "structure_bias": structure["structure_bias"],
            "buildup": structure["buildup"],
        },
        "volume": vol_regime,
        "futures": futures,
        "htf": htf,
        "session": {
            "vwap": vwap,
            "ema20": ema20,
            "atr": atr,
            "vwap_dev_pct": metrics.get("vwap_dev_pct") if vwap == metrics.get("vwap") else (
                round((spot - _f(vwap)) / _f(vwap) * 100.0, 3) if vwap else None
            ),
            "orh": or_session.get("orh"),
            "orl": or_session.get("orl"),
            "or_mid": or_session.get("mid"),
            "or_valid": bool(or_session.get("valid")),
            "or_bars": or_session.get("bars"),
            "or_break_state": or_session.get("break_state"),
            "or_confirmed": bool(or_session.get("confirmed")),
            "or_reason": or_session.get("reason"),
            "clean_room": or_session.get("room"),
        },
        "anomalies": anomalies,
        "top_anomaly": top,
        "trade": trade,
        "why_not": why_not,
        "digest": digest,
        "pass_id": snapshot.get("pass_id"),
        "engine": "v6-anomaly",
    }
    body["max_oi_added"] = _max_session_delta_oi(chain)
    body["setup_score"] = setup_score(body)
    body["flags"] = screen_flags(body)
    return body


def setup_score(report: Dict[str, Any]) -> int:
    """0–100 rank for the board. Incorporates Footstep Score, Wall+volume setups, and real momentum."""
    grade = report.get("grade")
    score = 0.0
    if grade == GRADE_TRADEABLE:
        score += 35.0
    elif grade == GRADE_WATCH:
        score += 15.0

    top = report.get("top_anomaly") or {}
    kind = top.get("type")
    anoms = report.get("anomalies") or []
    types = {a.get("type") for a in anoms}
    for a in anoms:
        types.update(a.get("types") or [])

    # Anomaly weights
    if kind in ("WALL_SUPPORT", "WALL_RESISTANCE"):
        score += 18.0
    elif kind in ("OR_BREAK_LONG", "OR_BREAK_SHORT"):
        score += 24.0
    elif "FOOTSTEP_EARLY" in types or kind == "FOOTSTEP_EARLY":
        score += 20.0
    elif kind == "CLUSTER":
        score += 14.0
    elif "VOR_SHOCK" in types or kind == "VOR_SHOCK":
        score += 15.0
    elif kind == "HIGH_STRIKE_VOL":
        score += 10.0
    elif kind in ("SIZE", "OTM_SIZE"):
        score += 8.0

    # VOR bonus
    vor = _f(top.get("vor"))
    if vor >= 0.8:
        score += 12.0
    elif vor >= 0.5:
        score += 7.0

    score += min(14.0, abs(_f(top.get("oi_added"))) / 15_000.0)
    vol = report.get("volume") or {}
    vs = _f(vol.get("vs_avg") or vol.get("vs_prev"))
    if vs >= 1.2:
        score += min(12.0, (vs - 1.0) * 8.0)
    if vol.get("expanded"):
        score += 6.0
    if report.get("trade"):
        score += 10.0
    if report.get("chain_bias") == BIAS_CONFLICT:
        score -= 18.0
    rr = _f((report.get("trade") or {}).get("rr"))
    if rr >= 1.2:
        score += 4.0
    return int(max(0, min(100, round(score))))


def _max_session_delta_oi(chain: Sequence[Dict[str, Any]]) -> float:
    """Largest |session ΔOI| on any CE/PE leg. Not gated on volume."""
    mx = 0.0
    for row in chain or []:
        for key in ("call", "put"):
            opt = row.get(key) or {}
            added = abs(_oi_added(opt, None))
            if added > mx:
                mx = added
    return mx


def _near_wall(spot: float, wall: Any, pct: float = WALL_NEAR_PCT) -> bool:
    if not wall or not spot:
        return False
    return abs(_f(wall) - float(spot)) / float(spot) * 100.0 <= pct


def htf_gate_allows(
    futures: Optional[Dict[str, Any]],
    htf: Optional[Dict[str, Any]],
    direction: str,
) -> bool:
    d = (direction or "").upper()
    h = htf or {}
    f = futures or {}
    if d == BIAS_BULL:
        return (
            h.get("gate") == "ALLOW_LONG"
            or h.get("daily") == BIAS_BULL
            or h.get("h4") == BIAS_BULL
            or f.get("futures_bias") == BIAS_BULL
        )
    if d == BIAS_BEAR:
        return (
            h.get("gate") == "ALLOW_SHORT"
            or h.get("daily") == BIAS_BEAR
            or h.get("h4") == BIAS_BEAR
            or f.get("futures_bias") == BIAS_BEAR
        )
    return False


def screen_flags(report: Dict[str, Any]) -> Dict[str, Any]:
    """Four independent AND-able filters with exclusive, non-inflated tags.

    high_oi     large session ΔOI exceeding liquidity bucket floor
    high_vol    high present CE+PE option volume on this chain (not history)
    support     spot sitting on a confirmed put wall, or a WALL_SUPPORT print
    resistance  spot sitting on a confirmed call wall, or a WALL_RESISTANCE print
    """
    anoms = list(report.get("anomalies") or [])
    types = {a.get("type") for a in anoms}
    for a in anoms:
        types.update(a.get("types") or [])
    vol = report.get("volume") or {}
    st = report.get("structure") or {}
    fut = report.get("futures") or {}
    bucket = report.get("bucket") or liquidity_bucket(str(report.get("symbol") or ""))
    oi_floor, vol_floor = size_floors(bucket)
    max_oi = abs(_f(report.get("max_oi_added")))
    max_pct = 0.0
    support_strike = st.get("put_wall")
    resist_strike = st.get("call_wall")
    hottest_vor = 0.0
    hottest_vel = 0.0
    for a in anoms:
        added = abs(_f(a.get("oi_added")))
        pct = abs(_f(a.get("oi_change_pct")))
        vor_val = _f(a.get("vor"))
        vel_val = abs(_f(a.get("oi_velocity")))
        if added > max_oi:
            max_oi = added
        if pct > max_pct:
            max_pct = pct
        if vor_val > hottest_vor:
            hottest_vor = vor_val
        if vel_val > hottest_vel:
            hottest_vel = vel_val
        if a.get("type") == "WALL_SUPPORT":
            support_strike = a.get("strike") or a.get("wall") or support_strike
        if a.get("type") == "WALL_RESISTANCE":
            resist_strike = a.get("strike") or a.get("wall") or resist_strike

    tot = _f(vol.get("total_volume") or report.get("chain_volume"))
    # High OI: large session ΔOI exceeding liquidity bucket floor
    high_oi = max_oi >= oi_floor or (max_oi >= oi_floor * 0.5 and max_pct >= MIN_OI_PCT)
    # High Vol: scaled against liquidity bucket floor
    high_vol = tot >= float(HIGH_CHAIN_VOL.get(bucket, HIGH_CHAIN_VOL[BUCKET_REST]))
    spot = _f(report.get("spot"))
    support = "WALL_SUPPORT" in types
    resistance = "WALL_RESISTANCE" in types

    buildup_primary = str((st.get("buildup") or {}).get("primary_state") or report.get("buildup_primary") or "").lower()
    skew = _f(st.get("iv_skew"))
    oi_pcr = _f(st.get("oi_pcr"), 1.0)
    vol_x = _f((vol or {}).get("hottest_vol_x") or (vol or {}).get("vs_avg"), 1.0)
    vs_avg = _f((vol or {}).get("vs_avg"), 0.0)

    # Detect Short Squeeze
    fut_state = str(fut.get("state") or "").upper()
    squeeze_active = (fut_state == "SHORT_COVERING" and report.get("chain_bias") == BIAS_BULL)

    call_buying = (
        ("call buying" in buildup_primary or "long buildup" in buildup_primary)
        and report.get("chain_bias") == BIAS_BULL
        and not any(a.get("exhaustion") for a in anoms if a.get("side") == "CE")
    )
    put_writing = ("put writing" in buildup_primary) and support
    short_covering = ("short covering" in buildup_primary or fut_state == "SHORT_COVERING") and not squeeze_active
    call_writing = ("call writing" in buildup_primary) and resistance

    early_mover = "FOOTSTEP_EARLY" in types
    vol_spike = vs_avg >= 2.0 or vol_x >= 3.0 or "VOR_SHOCK" in types
    oi_spike = high_oi and (max_pct >= 25.0 or hottest_vel >= 2000)
    skew_pop = abs(skew) >= 3.0
    sess = report.get("session") or {}
    or_state = str(sess.get("or_break_state") or "")
    or_break_long = "OR_BREAK_LONG" in types or or_state == "OR_BREAK_LONG"
    or_break_short = "OR_BREAK_SHORT" in types or or_state == "OR_BREAK_SHORT"
    premium_expansion = any(
        _f(a.get("ltp_chg_pct")) >= PREMIUM_CONFIRM_PCT
        and a.get("direction") in (BIAS_BULL, BIAS_BEAR)
        and not a.get("exhaustion")
        for a in anoms
    )
    clean_room = bool((sess.get("clean_room") or {}).get("clean"))
    htf_aligned = (
        report.get("chain_bias") == BIAS_BULL and htf_gate_allows(fut, report.get("htf"), BIAS_BULL)
    ) or (
        report.get("chain_bias") == BIAS_BEAR and htf_gate_allows(fut, report.get("htf"), BIAS_BEAR)
    )

    # Exclusive Ranked Tag Assignment:
    # 1. Primary Intent Tag (Exactly one)
    primary_tag = None
    if or_break_long:
        primary_tag = "OR_BREAK_LONG"
    elif or_break_short:
        primary_tag = "OR_BREAK_SHORT"
    elif squeeze_active:
        primary_tag = "SQUEEZE_ACTIVE"
    elif early_mover:
        primary_tag = "EARLY_MOVER"
    elif call_buying:
        primary_tag = "CALL_BUYING"
    elif put_writing:
        primary_tag = "PUT_FLOOR"
    elif short_covering:
        primary_tag = "SHORT_COVER"
    elif call_writing:
        primary_tag = "CALL_CEILING"

    # 2. Location Tag (At most one)
    loc_tag = None
    if "WALL_BREAK" in types:
        loc_tag = "WALL_BREAK"
    elif support:
        loc_tag = "SUPPORT"
    elif resistance:
        loc_tag = "RESISTANCE"
    elif "CLUSTER" in types:
        loc_tag = "CLUSTER"

    # 3. Size / Vol Shock Tag (At most one)
    size_tag = None
    if vol_spike or hottest_vor >= 0.8:
        size_tag = "VOL_SURGE"
    elif oi_spike:
        size_tag = "OI_SURGE"
    elif skew_pop:
        size_tag = "SKEW_POP"

    tags = []
    if primary_tag: tags.append(primary_tag)
    if loc_tag and loc_tag not in tags: tags.append(loc_tag)
    if size_tag and size_tag not in tags: tags.append(size_tag)
    if premium_expansion and "PREMIUM_EXPANSION" not in tags:
        tags.append("PREMIUM_EXPANSION")
    if clean_room and "CLEAN_ROOM" not in tags:
        tags.append("CLEAN_ROOM")
    if htf_aligned and "HTF_ALIGNED" not in tags:
        tags.append("HTF_ALIGNED")
    if not tags:
        tags.append("TRADEABLE" if report.get("grade") == GRADE_TRADEABLE else "WATCH" if report.get("grade") == GRADE_WATCH else "QUIET")

    return {
        "high_oi": bool(high_oi),
        "high_vol": bool(high_vol),
        "support": bool(support),
        "resistance": bool(resistance),
        "call_buying": bool(call_buying),
        "put_writing": bool(put_writing),
        "short_covering": bool(short_covering),
        "call_writing": bool(call_writing),
        "early_mover": bool(early_mover),
        "or_break_long": bool(or_break_long),
        "or_break_short": bool(or_break_short),
        "premium_expansion": bool(premium_expansion),
        "clean_room": bool(clean_room),
        "htf_aligned": bool(htf_aligned),
        "vol_spike": bool(vol_spike),
        "oi_spike": bool(oi_spike),
        "skew_pop": bool(skew_pop),
        "squeeze_active": bool(squeeze_active),
        "tags": tags,
        "oi_added": round(max_oi, 0),
        "opt_volume": round(tot, 0),
        "vol_x": vol_x,
        "vor": hottest_vor,
        "oi_velocity": hottest_vel,
        "support_strike": support_strike,
        "resistance_strike": resist_strike,
        "unique": False,
        "unique_score": 0.0,
    }


def apply_universe_rank(hits: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cross-sectional uniqueness vs this harvest. Mutates flags in place."""
    rows = [h for h in hits if h]
    if not rows:
        return list(hits)

    def _pct(values: List[float], x: float) -> float:
        if not values:
            return 0.0
        n = sum(1 for v in values if v <= x)
        return n / float(len(values))

    by_bucket: Dict[str, List[Dict[str, Any]]] = {}
    for h in rows:
        by_bucket.setdefault(str(h.get("bucket") or BUCKET_REST), []).append(h)

    for group in by_bucket.values():
        scores = [float(h.get("setup_score") or 0) for h in group]
        ois = [float(((h.get("flags") or {}).get("oi_added") or 0)) for h in group]
        vors = [float(((h.get("flags") or {}).get("vor") or h.get("vor") or 0)) for h in group]
        volxs = [float(((h.get("flags") or {}).get("vol_x") or h.get("vol_x") or 0)) for h in group]
        for h in group:
            flags = dict(h.get("flags") or {})
            sc = float(h.get("setup_score") or 0)
            oi = float(flags.get("oi_added") or 0)
            vor = float(flags.get("vor") or h.get("vor") or 0)
            vx = float(flags.get("vol_x") or h.get("vol_x") or 0)
            us = (
                _pct(scores, sc) * 0.40
                + _pct(ois, oi) * 0.25
                + _pct(vors, vor) * 0.20
                + _pct(volxs, vx) * 0.15
            )
            unique = us >= UNIQUE_SCORE_FLOOR
            flags["unique_score"] = round(us, 3)
            flags["unique"] = unique
            tags = list(flags.get("tags") or [])
            if unique and "UNIQUE" not in tags:
                tags.append("UNIQUE")
            if not unique and "UNIQUE" in tags:
                tags = [t for t in tags if t != "UNIQUE"]
            flags["tags"] = tags
            h["flags"] = flags
            h["unique_score"] = round(us, 3)
            if unique and not h.get("_unique_bonus"):
                h["setup_score"] = int(min(100, int(h.get("setup_score") or 0) + 10))
                h["_unique_bonus"] = True
    return list(hits)


def primary_tag_of(row: Dict[str, Any]) -> Optional[str]:
    tags = ((row.get("flags") or {}).get("tags") or [])
    primary = {
        "OR_BREAK_LONG", "OR_BREAK_SHORT", "SQUEEZE_ACTIVE", "EARLY_MOVER",
        "FOOTSTEP_EARLY", "CALL_BUYING", "PUT_FLOOR", "SHORT_COVER", "CALL_CEILING",
    }
    for t in tags:
        if t in primary:
            return t
    return None


def cap_screen_by_tag(rows: Sequence[Dict[str, Any]], cap: int = UNIQUE_TAG_CAP) -> List[Dict[str, Any]]:
    """Keep at most `cap` names per primary tag, preferring unique + score."""
    ranked = sorted(
        rows,
        key=lambda r: (
            0 if (r.get("flags") or {}).get("unique") else 1,
            0 if r.get("grade") == GRADE_TRADEABLE else 1,
            -float(r.get("unique_score") or 0),
            -float(r.get("setup_score") or 0),
        ),
    )
    seen: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for r in ranked:
        tag = primary_tag_of(r) or "_"
        n = seen.get(tag, 0)
        if n >= cap:
            continue
        seen[tag] = n + 1
        out.append(r)
    return out


def summarize_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Board row — keep the wire clean and fully enriched with signal interpretations."""
    from app.services.signal_interpreter import (
        interpret_pcr,
        interpret_iv_skew,
        interpret_buildup,
    )

    trade = report.get("trade") or {}
    top = report.get("top_anomaly") or {}
    st = report.get("structure") or {}
    fut = report.get("futures") or {}
    score = report.get("setup_score")
    if score is None:
        score = setup_score(report)
    flags = report.get("flags") or screen_flags(report)

    # Signal interpretations
    pcr_info = interpret_pcr(st.get("oi_pcr"), vol_pcr=st.get("vol_pcr"))
    skew_info = interpret_iv_skew(st.get("iv_skew"))
    buildup_info = interpret_buildup(st.get("buildup_primary"), (st.get("buildup") or {}).get("conviction"))

    top_label = top.get("label") or top.get("type") or "No Anomaly"
    top_vor = _f(top.get("vor")) or _f(flags.get("vor"))

    return {
        "symbol": report.get("symbol"),
        "name": report.get("name"),
        "ts": report.get("ts"),
        "spot": report.get("spot"),
        "atm": report.get("atm"),
        "dte": report.get("dte"),
        "grade": report.get("grade"),
        "bucket": report.get("bucket"),
        "chain_bias": report.get("chain_bias"),
        "snapshot_intent": report.get("snapshot_intent"),
        "regime": st.get("regime"),
        "pcr_label": pcr_info.get("label"),
        "pcr_sentence": pcr_info.get("sentence"),
        "pcr_color": pcr_info.get("color"),
        "skew_sentence": skew_info.get("sentence"),
        "skew_color": skew_info.get("color"),
        "buildup_badge": buildup_info.get("badge"),
        "buildup_sentence": buildup_info.get("sentence"),
        "oi_pcr": st.get("oi_pcr"),
        "call_wall": st.get("call_wall"),
        "put_wall": st.get("put_wall"),
        "gamma_wall": st.get("gamma_wall"),
        "futures_state": fut.get("state"),
        "futures_ok": fut.get("ok"),
        "session": report.get("session") or {},
        "top_anomaly": {
            "type": top.get("type"),
            "side": top.get("side"),
            "strike": top.get("strike"),
            "label": top_label,
            "oi_added": top.get("oi_added"),
            "vol_x": top.get("vol_x"),
            "vor": top_vor,
            "oi_velocity": top.get("oi_velocity"),
            "volume": top.get("volume"),
        } if top else None,
        "top_anomaly_label": top_label,
        "setup_score": int(score),
        "flags": flags,
        "trade": trade or None,
        "why_not": report.get("why_not"),
        "volume": report.get("volume") or {},
        "vol_x_avg": (report.get("volume") or {}).get("vs_avg")
        or (report.get("volume") or {}).get("hottest_vol_x")
        or (flags or {}).get("vol_x"),
        "vol_x": (flags or {}).get("vol_x")
        or (report.get("volume") or {}).get("hottest_vol_x"),
        "vor": top_vor,
        "chain_volume": (report.get("volume") or {}).get("total_volume"),
        "engine": "v6-anomaly",
    }
