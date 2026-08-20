"""
Institutional levels map for NSE F&O.

Slow clock — computed from previous session OHLC + live structure.
These levels do not flicker with option-chain snapshots.

Includes:
  • Classic floor pivots (P, S1–S3, R1–R3)
  • Camarilla (S1–S4, R1–R4, H5/L5)
  • Central Pivot Range (CPR / TC–P–BC) — Indian desk staple
  • PDH / PDL / PDC + weekly pivot
  • ATR (14) and daily 7/20 SMA bias
  • Session VWAP ±1σ/±2σ and 15-min Opening Range
  • Option structure: put/call walls, max pain, gamma wall, PCR
  • Level clustering (institutional zones)
  • Location confluence vs a directional thesis
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, time, timedelta
from typing import Any, Dict, List, Optional, Tuple

import pytz

from app.services.option_analytics import (
    compute_greeks_walls,
    compute_max_pain,
    compute_professional_pcr,
    compute_structure_walls,
)
from app.utils.market_hours import IST

logger = logging.getLogger(__name__)

MONTH_CODES = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

INDEX_FUT_ROOT = {
    "NSE:NIFTY50-INDEX": "NIFTY",
    "NSE:NIFTYBANK-INDEX": "BANKNIFTY",
    "NSE:FINNIFTY-INDEX": "FINNIFTY",
    "NSE:MIDCPNIFTY-INDEX": "MIDCPNIFTY",
}

# Location score weights (flow.md §5 Layer C, cap 11 + cluster)
W_PIVOT = 2.0
W_OI_WALL = 2.0
W_VWAP = 2.0
W_CAM = 2.0
W_BREAK = 1.0
W_HTF = 1.0
W_MA = 1.0
W_CPR = 1.0
W_WEEKLY = 1.0
W_CLUSTER = 3.0
LOCATION_CAP = 11.0

# Spot is "at" a level if within this ATR fraction
AT_LEVEL_ATR = 0.30
CLUSTER_ATR = 0.20


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _candle_dt(c: Dict[str, Any]) -> Optional[datetime]:
    raw = c.get("datetime") or c.get("timestamp")
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 1e12:
                ts /= 1000.0
            dt = datetime.fromtimestamp(ts)
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if dt.tzinfo is not None:
                dt = dt.astimezone(IST).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def last_thursday(year: int, month: int) -> datetime:
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() != 3:  # Thursday
        d -= timedelta(days=1)
    return d


def nearest_monthly_fut_root_month(now: Optional[datetime] = None) -> Tuple[int, int]:
    """Return (yy, month_index_0) for the front-month futures contract."""
    now = now or datetime.now(IST).replace(tzinfo=None)
    y, m = now.year, now.month
    exp = last_thursday(y, m)
    # Roll after expiry day (and during expiry session after 15:30 we already rolled next day)
    if now.date() > exp.date():
        if m == 12:
            return (y + 1) % 100, 0
        return y % 100, m  # m is 1-based; next month index = m
    return y % 100, m - 1


def fut_symbol_for(underlying: str, now: Optional[datetime] = None) -> Optional[str]:
    """Fyers monthly futures symbol, e.g. NSE:SBIN25AUGFUT / NSE:NIFTY25AUGFUT."""
    yy, mi = nearest_monthly_fut_root_month(now)
    mon = MONTH_CODES[mi]
    if underlying in INDEX_FUT_ROOT:
        root = INDEX_FUT_ROOT[underlying]
        return f"NSE:{root}{yy:02d}{mon}FUT"
    if underlying.startswith("NSE:") and underlying.endswith("-EQ"):
        ticker = underlying.split(":")[-1].replace("-EQ", "")
        return f"NSE:{ticker}{yy:02d}{mon}FUT"
    if underlying.startswith("NSE:") and underlying.endswith("-INDEX"):
        ticker = underlying.split(":")[-1].replace("-INDEX", "")
        return f"NSE:{ticker}{yy:02d}{mon}FUT"
    return None


def compute_classic_pivots(high: float, low: float, close: float) -> Dict[str, float]:
    h, l, c = float(high), float(low), float(close)
    p = (h + l + c) / 3.0
    r1 = 2.0 * p - l
    s1 = 2.0 * p - h
    r2 = p + (h - l)
    s2 = p - (h - l)
    r3 = h + 2.0 * (p - l)
    s3 = l - 2.0 * (h - p)
    return {
        "P": round(p, 2),
        "R1": round(r1, 2),
        "S1": round(s1, 2),
        "R2": round(r2, 2),
        "S2": round(s2, 2),
        "R3": round(r3, 2),
        "S3": round(s3, 2),
    }


def compute_camarilla(high: float, low: float, close: float) -> Dict[str, float]:
    h, l, c = float(high), float(low), float(close)
    rng = h - l
    r4 = c + rng * 1.1 / 2.0
    r3 = c + rng * 1.1 / 4.0
    r2 = c + rng * 1.1 / 6.0
    r1 = c + rng * 1.1 / 12.0
    s1 = c - rng * 1.1 / 12.0
    s2 = c - rng * 1.1 / 6.0
    s3 = c - rng * 1.1 / 4.0
    s4 = c - rng * 1.1 / 2.0
    # Breakout extensions
    h5 = (h / l) * c if l else r4
    l5 = c - (h5 - c)
    return {
        "R4": round(r4, 2),
        "R3": round(r3, 2),
        "R2": round(r2, 2),
        "R1": round(r1, 2),
        "S1": round(s1, 2),
        "S2": round(s2, 2),
        "S3": round(s3, 2),
        "S4": round(s4, 2),
        "H5": round(h5, 2),
        "L5": round(l5, 2),
    }


def compute_cpr(high: float, low: float, close: float) -> Dict[str, Any]:
    h, l, c = float(high), float(low), float(close)
    p = (h + l + c) / 3.0
    bc = (h + l) / 2.0
    tc = (p - bc) + p
    # Ensure TC is the upper rail
    if tc < bc:
        tc, bc = bc, tc
    width = abs(tc - bc)
    return {
        "P": round(p, 2),
        "TC": round(tc, 2),
        "BC": round(bc, 2),
        "width": round(width, 2),
    }


def compute_atr(dailies: List[Dict[str, Any]], period: int = 14) -> Optional[float]:
    if len(dailies) < 2:
        return None
    trs: List[float] = []
    for i in range(1, len(dailies)):
        h = _f(dailies[i].get("high"))
        l = _f(dailies[i].get("low"))
        pc = _f(dailies[i - 1].get("close"))
        tr = max(h - l, abs(h - pc), abs(l - pc))
        if tr > 0:
            trs.append(tr)
    if not trs:
        return None
    window = trs[-period:] if len(trs) >= period else trs
    return round(sum(window) / len(window), 4)


def sma(values: List[float], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    chunk = values[-period:]
    return round(sum(chunk) / period, 4)


def session_vwap_and_bands(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candles:
        return {"vwap": None, "sigma": None, "upper_1": None, "lower_1": None, "upper_2": None, "lower_2": None}
    num = 0.0
    den = 0.0
    tps: List[float] = []
    vols: List[float] = []
    for c in candles:
        h, l, cl = _f(c.get("high")), _f(c.get("low")), _f(c.get("close"))
        v = _f(c.get("volume"))
        tp = (h + l + cl) / 3.0
        tps.append(tp)
        vols.append(v)
        num += tp * v
        den += v
    if den <= 0:
        vwap = sum(tps) / len(tps) if tps else None
    else:
        vwap = num / den
    if vwap is None:
        return {"vwap": None, "sigma": None, "upper_1": None, "lower_1": None, "upper_2": None, "lower_2": None}
    # Volume-weighted variance around VWAP
    var_num = 0.0
    for tp, v in zip(tps, vols):
        w = v if den > 0 and v > 0 else 1.0
        var_num += w * (tp - vwap) ** 2
    var_den = den if den > 0 else float(len(tps))
    sigma = math.sqrt(var_num / var_den) if var_den > 0 else 0.0
    return {
        "vwap": round(vwap, 2),
        "sigma": round(sigma, 4),
        "upper_1": round(vwap + sigma, 2),
        "lower_1": round(vwap - sigma, 2),
        "upper_2": round(vwap + 2 * sigma, 2),
        "lower_2": round(vwap - 2 * sigma, 2),
    }


def opening_range(candles_5m: List[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, Any]:
    """First 15 minutes (09:15–09:30 IST) high/low."""
    now = now or datetime.now(IST).replace(tzinfo=None)
    today = now.date()
    or_bars: List[Dict[str, Any]] = []
    for c in candles_5m or []:
        dt = _candle_dt(c)
        if dt is None or dt.date() != today:
            continue
        t = dt.time()
        if time(9, 15) <= t < time(9, 30):
            or_bars.append(c)
    if len(or_bars) < 2:
        return {"orh": None, "orl": None, "valid": False, "bars": len(or_bars)}
    orh = max(_f(c.get("high")) for c in or_bars)
    orl = min(_f(c.get("low")) for c in or_bars)
    return {
        "orh": round(orh, 2),
        "orl": round(orl, 2),
        "valid": now.time() >= time(9, 30),
        "bars": len(or_bars),
        "mid": round((orh + orl) / 2.0, 2),
    }


def classify_camarilla_regime(spot: float, cam: Dict[str, float]) -> str:
    if not cam or not spot:
        return "UNKNOWN"
    r4, s4 = cam.get("R4"), cam.get("S4")
    r3, s3 = cam.get("R3"), cam.get("S3")
    if r4 and spot > r4:
        return "TREND_UP"
    if s4 and spot < s4:
        return "TREND_DN"
    if r3 and s3 and s3 <= spot <= r3:
        return "INSIDE_CAM"
    if r3 and r4 and r3 < spot <= r4:
        return "CAM_UPPER"
    if s4 and s3 and s4 <= spot < s3:
        return "CAM_LOWER"
    return "INSIDE_CAM"


def classify_pivot_side(spot: float, p: Optional[float], atr: float) -> str:
    if not p or not spot:
        return "AT_P"
    band = max(atr * 0.15, abs(p) * 0.0008)
    if spot > p + band:
        return "ABOVE_P"
    if spot < p - band:
        return "BELOW_P"
    return "AT_P"


def _near(spot: float, level: Optional[float], atr: float, frac: float = AT_LEVEL_ATR) -> bool:
    if level is None or spot <= 0:
        return False
    tol = max(atr * frac, abs(spot) * 0.0006)
    return abs(spot - level) <= tol


def flatten_levels(day: Dict[str, Any], session: Dict[str, Any], structure: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Named price levels used for clustering + UI."""
    out: List[Dict[str, Any]] = []

    def add(name: str, price: Any, family: str) -> None:
        p = _f(price) if price is not None else 0.0
        if p > 0:
            out.append({"name": name, "price": round(p, 2), "family": family})

    piv = day.get("pivots") or {}
    cam = day.get("camarilla") or {}
    cpr = day.get("cpr") or {}
    add("P", piv.get("P"), "pivot")
    for k in ("S1", "S2", "S3", "R1", "R2", "R3"):
        add(k, piv.get(k), "pivot")
    for k in ("S3", "S4", "R3", "R4"):
        add(f"CAM_{k}", cam.get(k), "camarilla")
    add("CPR_TC", cpr.get("TC"), "cpr")
    add("CPR_BC", cpr.get("BC"), "cpr")
    add("PDH", day.get("pdh"), "prev_day")
    add("PDL", day.get("pdl"), "prev_day")
    add("PDC", day.get("pdc"), "prev_day")
    add("WP", day.get("weekly_p"), "weekly")
    add("VWAP", session.get("vwap"), "vwap")
    add("ORH", session.get("orh"), "opening")
    add("ORL", session.get("orl"), "opening")
    add("PUT_WALL", structure.get("put_wall"), "oi_wall")
    add("CALL_WALL", structure.get("call_wall"), "oi_wall")
    add("MAX_PAIN", structure.get("max_pain"), "max_pain")
    add("GAMMA_WALL", structure.get("gamma_wall"), "gamma")
    return out


def cluster_levels(levels: List[Dict[str, Any]], atr: float) -> List[Dict[str, Any]]:
    """Merge independent families within 0.2 ATR into institutional zones."""
    if not levels:
        return []
    tol = max(atr * CLUSTER_ATR, 1.0)
    ordered = sorted(levels, key=lambda x: x["price"])
    clusters: List[Dict[str, Any]] = []
    cur: List[Dict[str, Any]] = [ordered[0]]
    for lv in ordered[1:]:
        if abs(lv["price"] - cur[-1]["price"]) <= tol:
            cur.append(lv)
        else:
            clusters.append(_pack_cluster(cur))
            cur = [lv]
    clusters.append(_pack_cluster(cur))
    # Institutional = 2+ distinct families
    for c in clusters:
        families = {x["family"] for x in c["members"]}
        c["families"] = sorted(families)
        c["institutional"] = len(families) >= 2
        c["strength"] = len(families)
    return [c for c in clusters if c["institutional"]]


def _pack_cluster(members: List[Dict[str, Any]]) -> Dict[str, Any]:
    prices = [m["price"] for m in members]
    lo, hi = min(prices), max(prices)
    return {
        "low": round(lo, 2),
        "high": round(hi, 2),
        "mid": round((lo + hi) / 2.0, 2),
        "members": members,
        "labels": [m["name"] for m in members],
    }


def score_location(
    *,
    spot: float,
    direction: str,
    day: Dict[str, Any],
    session: Dict[str, Any],
    structure: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Independent location vote for a directional thesis.
    Does not use LIS / OI% / premium — those are the fuel clock.
    """
    d = (direction or "NEUTRAL").upper()
    atr = _f(day.get("atr")) or max(abs(spot) * 0.008, 1.0)
    piv = day.get("pivots") or {}
    cam = day.get("camarilla") or {}
    cpr = day.get("cpr") or {}
    tags: List[str] = []
    score = 0.0
    breakdown: Dict[str, float] = {}

    p = piv.get("P")
    s1, s2 = piv.get("S1"), piv.get("S2")
    r1, r2 = piv.get("R1"), piv.get("R2")
    put_wall = structure.get("put_wall")
    call_wall = structure.get("call_wall")
    vwap = session.get("vwap")
    orh, orl = session.get("orh"), session.get("orl")
    pdh, pdl = day.get("pdh"), day.get("pdl")
    cam_reg = classify_camarilla_regime(spot, cam)
    pivot_side = classify_pivot_side(spot, p, atr)

    # Institutional cluster at spot
    levels = flatten_levels(day, session, structure)
    zones = cluster_levels(levels, atr)
    at_zone = None
    for z in zones:
        if z["low"] - atr * 0.15 <= spot <= z["high"] + atr * 0.15:
            at_zone = z
            break
    if at_zone:
        score += W_CLUSTER
        breakdown["cluster"] = W_CLUSTER
        tags.append("INST_ZONE:" + "+".join(at_zone["labels"][:4]))

    # Classic pivot
    if d == "BULLISH":
        if _near(spot, s1, atr) or _near(spot, s2, atr) or _near(spot, p, atr):
            score += W_PIVOT
            breakdown["pivot"] = W_PIVOT
            tags.append("PIVOT_SUPPORT")
    elif d == "BEARISH":
        if _near(spot, r1, atr) or _near(spot, r2, atr) or _near(spot, p, atr):
            score += W_PIVOT
            breakdown["pivot"] = W_PIVOT
            tags.append("PIVOT_RESIST")

    # OI walls
    if d == "BULLISH" and put_wall and (_near(spot, put_wall, atr) or spot >= put_wall):
        # At or reclaimed above put wall
        if _near(spot, put_wall, atr) or 0 <= (spot - put_wall) <= atr * 0.6:
            score += W_OI_WALL
            breakdown["oi_wall"] = W_OI_WALL
            tags.append("PUT_WALL")
    elif d == "BEARISH" and call_wall and (_near(spot, call_wall, atr) or spot <= call_wall):
        if _near(spot, call_wall, atr) or 0 <= (call_wall - spot) <= atr * 0.6:
            score += W_OI_WALL
            breakdown["oi_wall"] = W_OI_WALL
            tags.append("CALL_WALL")

    # VWAP
    if vwap:
        if d == "BULLISH" and (spot >= vwap or _near(spot, vwap, atr)):
            score += W_VWAP
            breakdown["vwap"] = W_VWAP
            tags.append("VWAP_LONG")
        elif d == "BEARISH" and (spot <= vwap or _near(spot, vwap, atr)):
            score += W_VWAP
            breakdown["vwap"] = W_VWAP
            tags.append("VWAP_SHORT")

    # Camarilla regime must agree: fade inside, trend outside
    if d == "BULLISH":
        if cam_reg in ("TREND_UP", "CAM_UPPER") or (
            cam_reg == "INSIDE_CAM" and (_near(spot, cam.get("S3"), atr) or _near(spot, cam.get("S4"), atr))
        ):
            score += W_CAM
            breakdown["camarilla"] = W_CAM
            tags.append(f"CAM:{cam_reg}")
    elif d == "BEARISH":
        if cam_reg in ("TREND_DN", "CAM_LOWER") or (
            cam_reg == "INSIDE_CAM" and (_near(spot, cam.get("R3"), atr) or _near(spot, cam.get("R4"), atr))
        ):
            score += W_CAM
            breakdown["camarilla"] = W_CAM
            tags.append(f"CAM:{cam_reg}")

    # Break levels
    if d == "BULLISH" and (
        (orh and session.get("or_valid") and spot >= orh)
        or (pdh and spot >= pdh)
    ):
        score += W_BREAK
        breakdown["break"] = W_BREAK
        tags.append("BREAK_HIGH")
    elif d == "BEARISH" and (
        (orl and session.get("or_valid") and spot <= orl)
        or (pdl and spot <= pdl)
    ):
        score += W_BREAK
        breakdown["break"] = W_BREAK
        tags.append("BREAK_LOW")

    # Daily HTF
    htf = (day.get("daily_bias") or "NEUTRAL").upper()
    if d == "BULLISH" and htf == "BULLISH":
        score += W_HTF
        breakdown["htf"] = W_HTF
        tags.append("HTF_AGREE")
    elif d == "BEARISH" and htf == "BEARISH":
        score += W_HTF
        breakdown["htf"] = W_HTF
        tags.append("HTF_AGREE")
    elif d in ("BULLISH", "BEARISH") and htf in ("BULLISH", "BEARISH") and htf != d:
        tags.append("HTF_OPPOSE")

    # Daily 7/20
    ma_side = (day.get("ma_side") or "NEUTRAL").upper()
    if d == ma_side and d in ("BULLISH", "BEARISH"):
        score += W_MA
        breakdown["ma"] = W_MA
        tags.append("MA_AGREE")

    # CPR
    tc, bc = cpr.get("TC"), cpr.get("BC")
    if d == "BULLISH" and tc and spot >= tc:
        score += W_CPR
        breakdown["cpr"] = W_CPR
        tags.append("ABOVE_CPR")
    elif d == "BEARISH" and bc and spot <= bc:
        score += W_CPR
        breakdown["cpr"] = W_CPR
        tags.append("BELOW_CPR")

    # Weekly pivot
    wp = day.get("weekly_p")
    if d == "BULLISH" and wp and spot >= wp:
        score += W_WEEKLY
        breakdown["weekly"] = W_WEEKLY
        tags.append("ABOVE_WP")
    elif d == "BEARISH" and wp and spot <= wp:
        score += W_WEEKLY
        breakdown["weekly"] = W_WEEKLY
        tags.append("BELOW_WP")

    score = round(min(LOCATION_CAP, score), 1)

    wall_side = "BETWEEN_WALLS"
    if put_wall and call_wall:
        if _near(spot, put_wall, atr):
            wall_side = "AT_PUT_WALL"
        elif _near(spot, call_wall, atr):
            wall_side = "AT_CALL_WALL"
        elif put_wall < spot < call_wall:
            wall_side = "BETWEEN_WALLS"
        elif spot <= put_wall:
            wall_side = "BELOW_PUT_WALL"
        elif spot >= call_wall:
            wall_side = "ABOVE_CALL_WALL"

    return {
        "score": score,
        "cap": LOCATION_CAP,
        "tags": tags,
        "breakdown": breakdown,
        "atr": round(atr, 4),
        "pivot_side": pivot_side,
        "camarilla_regime": cam_reg,
        "wall_side": wall_side,
        "at_institutional_zone": bool(at_zone),
        "zone": at_zone,
        "htf_opposes": "HTF_OPPOSE" in tags,
    }


def _level_catalog(
    day: Dict[str, Any],
    session: Dict[str, Any],
    structure: Dict[str, Any],
) -> List[Tuple[str, float]]:
    """Named institutional levels used for side-aware entry / target pick."""
    piv = day.get("pivots") or {}
    cam = day.get("camarilla") or {}
    items: List[Tuple[str, float]] = []

    def add(name: str, price: Any) -> None:
        p = _f(price) if price is not None else 0.0
        if p > 0:
            items.append((name, p))

    add("Put wall", structure.get("put_wall"))
    add("Call wall", structure.get("call_wall"))
    add("P", piv.get("P"))
    add("S1", piv.get("S1"))
    add("S2", piv.get("S2"))
    add("S3", piv.get("S3"))
    add("R1", piv.get("R1"))
    add("R2", piv.get("R2"))
    add("R3", piv.get("R3"))
    add("Cam S3", cam.get("S3"))
    add("Cam S4", cam.get("S4"))
    add("Cam R3", cam.get("R3"))
    add("Cam R4", cam.get("R4"))
    add("VWAP", session.get("vwap"))
    add("PDH", day.get("pdh"))
    add("PDL", day.get("pdl"))
    add("ORH", session.get("orh"))
    add("ORL", session.get("orl"))
    return items


def _closest(spot: float, named: List[Tuple[str, float]], *, below: bool) -> Optional[Tuple[str, float]]:
    """Nearest level strictly below (support) or strictly above (resistance)."""
    eps = max(abs(spot) * 0.0003, 0.05)
    pool = []
    for name, px in named:
        if below and px < spot - eps:
            pool.append((name, px))
        elif not below and px > spot + eps:
            pool.append((name, px))
    if not pool:
        return None
    if below:
        return max(pool, key=lambda x: x[1])  # closest support under spot
    return min(pool, key=lambda x: x[1])  # closest resistance over spot


def _next_out(
    spot: float,
    named: List[Tuple[str, float]],
    used: Optional[float],
    *,
    below: bool,
) -> Optional[Tuple[str, float]]:
    eps = max(abs(spot) * 0.0003, 0.05)
    skip = _f(used) if used else None
    pool = []
    for name, px in named:
        if skip is not None and abs(px - skip) < eps:
            continue
        if below and px < spot - eps and (skip is None or px < skip - eps):
            pool.append((name, px))
        elif not below and px > spot + eps and (skip is None or px > skip + eps):
            pool.append((name, px))
    if not pool:
        return None
    if below:
        return max(pool, key=lambda x: x[1])
    return min(pool, key=lambda x: x[1])


def _at_or_beyond(
    spot: float,
    named: List[Tuple[str, float]],
    prefer: List[str],
    *,
    above: bool,
) -> Optional[Tuple[str, float]]:
    """Entry / rejection: preferred names on the correct side, else nearest."""
    eps = max(abs(spot) * 0.003, 0.25)  # "at" the level
    preferred = []
    for name, px in named:
        if name not in prefer:
            continue
        if above and px >= spot - eps:
            preferred.append((name, px))
        if not above and px <= spot + eps:
            preferred.append((name, px))
    if preferred:
        if above:
            return min(preferred, key=lambda x: abs(x[1] - spot))
        return min(preferred, key=lambda x: abs(x[1] - spot))
    return _closest(spot, named, below=not above)


def invalidation_and_targets(
    *,
    spot: float,
    direction: str,
    day: Dict[str, Any],
    session: Dict[str, Any],
    structure: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Side-aware map.

    LONG:  entry = support / put wall. Target = resistance ABOVE (call wall, R1, Cam R3).
    SHORT: entry = resistance / call wall. Target = support BELOW (put wall, S1, Cam S3).
    A resistance print is never a short target.
    """
    atr = _f(day.get("atr")) or max(abs(spot) * 0.008, 1.0)
    named = _level_catalog(day, session, structure)
    d = (direction or "").upper()
    empty = {
        "invalidation": None,
        "stop": None,
        "target": None,
        "target_2": None,
        "target_label": None,
        "target_2_label": None,
        "entry": None,
        "entry_label": None,
        "risk_pts": None,
    }
    if d not in ("BULLISH", "BEARISH"):
        return empty

    if d == "BULLISH":
        entry = _at_or_beyond(
            spot, named,
            ["Put wall", "S1", "S2", "Cam S3", "VWAP", "ORL", "PDL", "P"],
            above=False,
        )
        t1 = _closest(spot, named, below=False)
        t2 = _next_out(spot, named, t1[1] if t1 else None, below=False)
        inv_px = entry[1] if entry else spot - atr
        stop = round(inv_px - 0.15 * atr, 2)
        return {
            "invalidation": round(inv_px, 2),
            "stop": stop,
            "entry": round(entry[1], 2) if entry else round(spot, 2),
            "entry_label": entry[0] if entry else "Spot",
            "target": round(t1[1], 2) if t1 else None,
            "target_label": t1[0] if t1 else None,
            "target_2": round(t2[1], 2) if t2 else None,
            "target_2_label": t2[0] if t2 else None,
            "risk_pts": round(spot - stop, 2),
        }

    # BEARISH — reject resistance, target support under the market
    entry = _at_or_beyond(
        spot, named,
        ["Call wall", "R1", "R2", "Cam R3", "VWAP", "ORH", "PDH", "P"],
        above=True,
    )
    t1 = _closest(spot, named, below=True)
    t2 = _next_out(spot, named, t1[1] if t1 else None, below=True)
    inv_px = entry[1] if entry else spot + atr
    stop = round(inv_px + 0.15 * atr, 2)
    return {
        "invalidation": round(inv_px, 2),
        "stop": stop,
        "entry": round(entry[1], 2) if entry else round(spot, 2),
        "entry_label": entry[0] if entry else "Spot",
        "target": round(t1[1], 2) if t1 else None,
        "target_label": t1[0] if t1 else None,
        "target_2": round(t2[1], 2) if t2 else None,
        "target_2_label": t2[0] if t2 else None,
        "risk_pts": round(stop - spot, 2),
    }


def daily_bias_from_candles(completed: List[Dict[str, Any]], p: Optional[float]) -> str:
    if len(completed) < 2:
        return "NEUTRAL"
    c1 = _f(completed[-1].get("close"))
    c2 = _f(completed[-2].get("close"))
    h1, l1 = _f(completed[-1].get("high")), _f(completed[-1].get("low"))
    h2, l2 = _f(completed[-2].get("high")), _f(completed[-2].get("low"))
    hh_hl = h1 > h2 and l1 > l2
    lh_ll = h1 < h2 and l1 < l2
    if hh_hl and c1 > c2:
        return "BULLISH"
    if lh_ll and c1 < c2:
        return "BEARISH"
    if p:
        if c1 > p * 1.001:
            return "BULLISH"
        if c1 < p * 0.999:
            return "BEARISH"
    return "NEUTRAL"


def build_day_map_from_dailies(
    dailies: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or datetime.now(IST).replace(tzinfo=None)
    today = now.date()
    completed: List[Dict[str, Any]] = []
    for c in dailies or []:
        dt = _candle_dt(c)
        if dt is None:
            continue
        if dt.date() < today:
            completed.append(c)
        elif dt.date() == today and now.time() >= time(15, 30):
            completed.append(c)
    if not completed:
        # fallback: use last candle even if dated today (weekend / missing stamps)
        if dailies:
            completed = list(dailies[:-1] or dailies[-1:])
        else:
            return {"ok": False, "reason": "no_daily_bars"}

    prev = completed[-1]
    h, l, c = _f(prev.get("high")), _f(prev.get("low")), _f(prev.get("close"))
    if h <= 0 or l <= 0 or c <= 0:
        return {"ok": False, "reason": "bad_ohlc"}

    pivots = compute_classic_pivots(h, l, c)
    cam = compute_camarilla(h, l, c)
    cpr = compute_cpr(h, l, c)
    atr = compute_atr(completed, 14) or round(h - l, 4)
    cpr_width_atr = (cpr["width"] / atr) if atr else None
    # Narrow CPR → trend-day tendency (Indian CPR doctrine)
    if cpr_width_atr is not None and cpr_width_atr < 0.35:
        cpr_regime = "NARROW_TREND"
    elif cpr_width_atr is not None and cpr_width_atr > 0.8:
        cpr_regime = "WIDE_RANGE"
    else:
        cpr_regime = "NORMAL"
    cpr["width_atr"] = round(cpr_width_atr, 3) if cpr_width_atr is not None else None
    cpr["regime"] = cpr_regime

    closes = [_f(x.get("close")) for x in completed if _f(x.get("close")) > 0]
    ma7 = sma(closes, 7)
    ma20 = sma(closes, 20)
    last = closes[-1] if closes else c
    if ma7 and ma20:
        if last > ma7 > ma20:
            ma_side = "BULLISH"
        elif last < ma7 < ma20:
            ma_side = "BEARISH"
        else:
            ma_side = "NEUTRAL"
    else:
        ma_side = "NEUTRAL"

    week = completed[-5:] if len(completed) >= 3 else completed
    wh = max(_f(x.get("high")) for x in week)
    wl = min(_f(x.get("low")) for x in week)
    wc = _f(week[-1].get("close"))
    weekly_p = round((wh + wl + wc) / 3.0, 2) if wh and wl and wc else None

    return {
        "ok": True,
        "session_date": str(today),
        "prev_date": str(_candle_dt(prev).date()) if _candle_dt(prev) else None,
        "pdh": round(h, 2),
        "pdl": round(l, 2),
        "pdc": round(c, 2),
        "pivots": pivots,
        "camarilla": cam,
        "cpr": cpr,
        "atr": atr,
        "weekly_p": weekly_p,
        "weekly_h": round(wh, 2),
        "weekly_l": round(wl, 2),
        "ma7": ma7,
        "ma20": ma20,
        "ma_side": ma_side,
        "daily_bias": daily_bias_from_candles(completed, pivots.get("P")),
    }


def build_session_map(
    candles_5m: List[Dict[str, Any]],
    spot: float,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or datetime.now(IST).replace(tzinfo=None)
    today = now.date()
    today_bars = []
    for c in candles_5m or []:
        dt = _candle_dt(c)
        if dt and dt.date() == today:
            today_bars.append(c)
    vw = session_vwap_and_bands(today_bars or candles_5m or [])
    orng = opening_range(candles_5m or [], now=now)
    vwap = vw.get("vwap")
    return {
        "vwap": vwap,
        "vwap_sigma": vw.get("sigma"),
        "vwap_u1": vw.get("upper_1"),
        "vwap_l1": vw.get("lower_1"),
        "vwap_u2": vw.get("upper_2"),
        "vwap_l2": vw.get("lower_2"),
        "vwap_side": (
            "VWAP_ABOVE" if vwap and spot >= vwap else "VWAP_BELOW" if vwap else "VWAP_UNKNOWN"
        ),
        "orh": orng.get("orh"),
        "orl": orng.get("orl"),
        "or_mid": orng.get("mid"),
        "or_valid": bool(orng.get("valid")),
        "or_bars": orng.get("bars"),
        "bars_used": len(today_bars),
    }


def build_structure_map(chain: List[Dict[str, Any]], spot: float) -> Dict[str, Any]:
    if not chain or not spot:
        return {}
    walls = compute_structure_walls(chain, spot)
    pain = compute_max_pain(chain)
    greeks = compute_greeks_walls(chain, spot)
    pcr = compute_professional_pcr(chain, spot=spot)
    max_pain = pain.get("max_pain")
    dte_pain = None
    if max_pain and spot:
        dte_pain = round(abs(max_pain - spot) / spot * 100.0, 3)
    return {
        "put_wall": walls.get("put_wall") or walls.get("support"),
        "put_wall_oi": walls.get("put_wall_oi") or walls.get("support_oi"),
        "call_wall": walls.get("call_wall") or walls.get("resistance"),
        "call_wall_oi": walls.get("call_wall_oi") or walls.get("resistance_oi"),
        "top_put_oi": walls.get("top_put_oi") or [],
        "top_call_oi": walls.get("top_call_oi") or [],
        "max_pain": max_pain,
        "max_pain_dist_pct": dte_pain,
        "gamma_wall": greeks.get("gamma_wall_strike"),
        "pin_risk": greeks.get("pin_risk"),
        "delta_bias": greeks.get("delta_bias"),
        "pcr": pcr.get("oi_pcr"),
        "vol_pcr": pcr.get("vol_pcr"),
        "pcr_regime": pcr.get("regime"),
        "pcr_label": pcr.get("regime_label"),
        "pcr_bias": pcr.get("oi_bias"),
    }


def classify_futures_buildup(
    price_change_pct: float,
    oi_change: Optional[float],
    oi: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Price ↑ + OI ↑ = long buildup
    Price ↓ + OI ↑ = short buildup
    Price ↑ + OI ↓ = short covering
    Price ↓ + OI ↓ = long unwinding
    """
    pc = _f(price_change_pct)
    if oi_change is None:
        return {
            "state": "UNKNOWN",
            "direction": "NEUTRAL",
            "label": "Futures OI unknown",
            "agree_long": False,
            "agree_short": False,
        }
    oc = _f(oi_change)
    oi_pct = (oc / oi * 100.0) if oi and oi > 0 else None
    # Tiny OI change is noise
    meaningful = abs(oc) >= 50_000 or (oi_pct is not None and abs(oi_pct) >= 1.5)
    if not meaningful:
        state, direction, label = "CHURN", "NEUTRAL", "Futures churn"
    elif pc > 0.05 and oc > 0:
        state, direction, label = "LONG_BUILDUP", "BULLISH", "Futures long buildup"
    elif pc < -0.05 and oc > 0:
        state, direction, label = "SHORT_BUILDUP", "BEARISH", "Futures short buildup"
    elif pc > 0.05 and oc < 0:
        state, direction, label = "SHORT_COVERING", "BULLISH", "Futures short covering"
    elif pc < -0.05 and oc < 0:
        state, direction, label = "LONG_UNWINDING", "BEARISH", "Futures long unwinding"
    else:
        state, direction, label = "CHURN", "NEUTRAL", "Futures mixed"
    return {
        "state": state,
        "direction": direction,
        "label": label,
        "price_change_pct": round(pc, 3),
        "oi_change": oc,
        "oi": oi,
        "oi_change_pct": round(oi_pct, 2) if oi_pct is not None else None,
        "agree_long": state in ("LONG_BUILDUP",),
        "agree_short": state in ("SHORT_BUILDUP",),
        # covering/unwinding is fuel-weak — do not treat as agreement
    }


class InstitutionalLevelsService:
    """Cached day/session/futures maps. Daily map lives until next IST date."""

    def __init__(self) -> None:
        self._day: Dict[str, Tuple[str, Dict[str, Any]]] = {}
        self._fut_last_oi: Dict[str, float] = {}
        self._fut_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
        self._FUT_TTL = 90.0

    def get_day_map(self, symbol: str) -> Dict[str, Any]:
        today = str(datetime.now(IST).date())
        hit = self._day.get(symbol)
        if hit and hit[0] == today and hit[1].get("ok"):
            return hit[1]
        try:
            from app.services import symbol_store as store

            dailies = store.get_history(symbol, "D", min_bars=15) or []
            if not dailies:
                # harvest writer may still fill D via fyers_market store-first
                from app.services.symbol_store import is_harvest_writer
                if is_harvest_writer():
                    from app.services.fyers_market import get_market_service

                    hist = get_market_service().get_historical_data(
                        symbol, resolution="D", days=30
                    )
                    dailies = hist.get("candles") or []
            if not dailies:
                return hit[1] if hit else {"ok": False, "reason": "no stored daily"}
            day = build_day_map_from_dailies(dailies)
        except Exception as exc:
            logger.debug("day map failed %s: %s", symbol, exc)
            day = {"ok": False, "reason": str(exc)}
        if day.get("ok"):
            self._day[symbol] = (today, day)
        return day

    def peek_day_map(self, symbol: str) -> Optional[Dict[str, Any]]:
        today = str(datetime.now(IST).date())
        hit = self._day.get(symbol)
        if hit and hit[0] == today:
            return hit[1]
        return None

    def get_futures(self, symbol: str) -> Dict[str, Any]:
        import time as _t

        now = _t.time()
        cached = self._fut_cache.get(symbol)
        if cached and now - cached[0] < self._FUT_TTL:
            return cached[1]
        try:
            from app.services import symbol_store as store

            snap = store.get(symbol) or {}
            stored_fut = snap.get("futures") or {}
            if stored_fut.get("ltp") and store.is_fresh(symbol, "futures", 300):
                packed = dict(stored_fut)
                if not packed.get("state"):
                    packed.update(classify_futures_buildup(
                        packed.get("change_pct") or packed.get("chg_pct"),
                        packed.get("oi_chg"),
                        packed.get("oi"),
                    ))
                packed.setdefault("ok", True)
                packed.setdefault("direction", packed.get("direction") or "NEUTRAL")
                packed.setdefault("agree_long", False)
                packed.setdefault("agree_short", False)
                self._fut_cache[symbol] = (now, packed)
                return packed
        except Exception:
            pass
        fut = fut_symbol_for(symbol)
        empty = {
            "ok": False,
            "symbol": fut,
            "state": "UNKNOWN",
            "direction": "NEUTRAL",
            "agree_long": False,
            "agree_short": False,
        }
        if not fut:
            return empty
        try:
            from app.services.symbol_store import is_harvest_writer

            if not is_harvest_writer():
                self._fut_cache[symbol] = (now, empty)
                return empty
            from app.services.fyers_market import get_market_service

            q = get_market_service().get_quotes([fut])
            row = None
            for item in q.get("data") or []:
                n = item.get("n") or item.get("v", {}).get("short_name") or ""
                if fut in str(n) or str(n).endswith(fut.split(":")[-1]):
                    row = item
                    break
            if row is None and q.get("data"):
                row = q["data"][0]
            if not row:
                self._fut_cache[symbol] = (now, empty)
                return empty
            v = row.get("v") or {}
            lp = _f(v.get("lp"))
            chp = _f(v.get("chp"))
            oi = v.get("oi")
            if oi is None:
                oi = v.get("open_interest")
            oi_f = _f(oi) if oi is not None else None
            prev_oi = v.get("poi") or v.get("prev_oi") or v.get("previous_oi")
            if prev_oi is not None:
                oi_chg = _f(oi_f) - _f(prev_oi) if oi_f is not None else None
            elif oi_f is not None and symbol in self._fut_last_oi:
                oi_chg = oi_f - self._fut_last_oi[symbol]
            else:
                oi_chg = None
            if oi_f is not None:
                self._fut_last_oi[symbol] = oi_f
            packed = classify_futures_buildup(chp, oi_chg, oi_f)
            packed.update({
                "ok": True,
                "symbol": fut,
                "ltp": lp,
                "change_pct": chp,
            })
            self._fut_cache[symbol] = (now, packed)
            try:
                from app.services import symbol_store as store

                store.put_futures(symbol, packed)
            except Exception:
                pass
            return packed
        except Exception as exc:
            logger.debug("futures quote failed %s: %s", symbol, exc)
            self._fut_cache[symbol] = (now, empty)
            return empty

    def build_full_map(
        self,
        symbol: str,
        spot: float,
        chain: Optional[List[Dict[str, Any]]] = None,
        candles_5m: Optional[List[Dict[str, Any]]] = None,
        *,
        fetch_day: bool = True,
        fetch_futures: bool = True,
    ) -> Dict[str, Any]:
        day = self.get_day_map(symbol) if fetch_day else (self.peek_day_map(symbol) or {"ok": False})
        session = build_session_map(candles_5m or [], spot)
        structure = build_structure_map(chain or [], spot)
        futures = self.get_futures(symbol) if fetch_futures else {
            "ok": False, "state": "UNKNOWN", "direction": "NEUTRAL",
            "agree_long": False, "agree_short": False,
        }
        levels = flatten_levels(day if day.get("ok") else {}, session, structure)
        atr = _f(day.get("atr")) or max(abs(spot) * 0.008, 1.0)
        zones = cluster_levels(levels, atr)
        return {
            "symbol": symbol,
            "spot": spot,
            "day": day,
            "session": session,
            "structure": structure,
            "futures": futures,
            "levels": levels,
            "zones": zones,
            "atr": atr,
            "pivot_side": classify_pivot_side(spot, (day.get("pivots") or {}).get("P"), atr),
            "camarilla_regime": classify_camarilla_regime(spot, day.get("camarilla") or {}),
        }


_levels_svc: Optional[InstitutionalLevelsService] = None


def get_levels_service() -> InstitutionalLevelsService:
    global _levels_svc
    if _levels_svc is None:
        _levels_svc = InstitutionalLevelsService()
    return _levels_svc
