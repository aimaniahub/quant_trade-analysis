"""
Multi-timeframe momentum engine.

Closed candles only. 4H owns allowed side. 15m times entry and cannot flip.
Daily MIXED is allowed; Daily HARD opposite is a veto.

Do not import Fyers here — this module is pure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.levels import _candle_dt, _f
from app.utils.market_hours import IST


def ema(values: List[float], period: int) -> Optional[float]:
    if not values or period <= 0 or len(values) < period:
        return None
    k = 2.0 / (period + 1)
    seed = sum(values[:period]) / period
    val = seed
    for x in values[period:]:
        val = x * k + val * (1.0 - k)
    return float(val)


def closed_candles(
    candles: List[Dict[str, Any]],
    period_minutes: int,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Drop the forming bar. Daily: drop today while the session is open."""
    if not candles:
        return []
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = IST.localize(now)
    else:
        now = now.astimezone(IST)
    now_naive = now.replace(tzinfo=None)

    if period_minutes >= 1440:
        out: List[Dict[str, Any]] = []
        for c in candles:
            dt = _candle_dt(c)
            if dt is None:
                continue
            if dt.date() < now_naive.date():
                out.append(c)
            elif dt.date() == now_naive.date() and now_naive.hour >= 15 and now_naive.minute >= 30:
                out.append(c)
        return out or list(candles[:-1] or candles)

    last = candles[-1]
    dt = _candle_dt(last)
    if dt is None:
        return list(candles)
    age = (now_naive - dt).total_seconds()
    # Bar is forming if it started less than one full period ago (minus 5s slack)
    if age < period_minutes * 60 - 5:
        return list(candles[:-1])
    return list(candles)


def _ohlc(c: Dict[str, Any]) -> Tuple[float, float, float]:
    return _f(c.get("high")), _f(c.get("low")), _f(c.get("close"))


def swing_points(
    candles: List[Dict[str, Any]],
    kind: str,
    lookback: int = 24,
) -> List[Tuple[int, float]]:
    """Fractal swing highs/lows on the last `lookback` bars."""
    if len(candles) < 5:
        return []
    window = candles[-lookback:] if len(candles) > lookback else candles
    offset = len(candles) - len(window)
    out: List[Tuple[int, float]] = []
    for i in range(1, len(window) - 1):
        h, l, _ = _ohlc(window[i])
        ph, pl, _ = _ohlc(window[i - 1])
        nh, nl, _ = _ohlc(window[i + 1])
        if kind == "low" and l < pl and l <= nl:
            out.append((offset + i, l))
        if kind == "high" and h > ph and h >= nh:
            out.append((offset + i, h))
    return out


def structure_label(candles: List[Dict[str, Any]]) -> str:
    """HH_HL / LH_LL / RANGE from the last two swings of each type."""
    lows = swing_points(candles, "low")
    highs = swing_points(candles, "high")
    hh = hl = lh = ll = False
    if len(highs) >= 2:
        if highs[-1][1] > highs[-2][1]:
            hh = True
        elif highs[-1][1] < highs[-2][1]:
            lh = True
    if len(lows) >= 2:
        if lows[-1][1] > lows[-2][1]:
            hl = True
        elif lows[-1][1] < lows[-2][1]:
            ll = True
    if hh and hl:
        return "HH_HL"
    if lh and ll:
        return "LH_LL"
    return "RANGE"


def higher_low(candles: List[Dict[str, Any]]) -> bool:
    lows = swing_points(candles, "low")
    if len(lows) < 2:
        return False
    return lows[-1][1] > lows[-2][1]


def lower_high(candles: List[Dict[str, Any]]) -> bool:
    highs = swing_points(candles, "high")
    if len(highs) < 2:
        return False
    return highs[-1][1] < highs[-2][1]


def last_swing_low(candles: List[Dict[str, Any]]) -> Optional[float]:
    lows = swing_points(candles, "low")
    return lows[-1][1] if lows else None


def last_swing_high(candles: List[Dict[str, Any]]) -> Optional[float]:
    highs = swing_points(candles, "high")
    return highs[-1][1] if highs else None


def momentum_state(candles: List[Dict[str, Any]], atr: Optional[float]) -> str:
    """EXPANDING / FLAT / COMPRESSING from last 3 bar ranges vs ATR."""
    if len(candles) < 3:
        return "FLAT"
    ranges = []
    for c in candles[-3:]:
        h, l, _ = _ohlc(c)
        ranges.append(max(h - l, 0.0))
    avg = sum(ranges) / 3.0
    ref = atr if atr and atr > 0 else (sum(ranges) / 3.0 or 1.0)
    ratio = avg / ref
    if ratio >= 0.85:
        return "EXPANDING"
    if ratio <= 0.45:
        return "COMPRESSING"
    return "FLAT"


def _frame_bias_ema(
    candles: List[Dict[str, Any]],
    *,
    fast: int,
    slow: int,
    hard_structure: bool,
) -> Dict[str, Any]:
    closes = [_f(c.get("close")) for c in candles if _f(c.get("close")) > 0]
    if len(closes) < slow:
        return {
            "ok": False,
            "bias": "MIXED",
            "hard": False,
            "structure": "RANGE",
            "price": closes[-1] if closes else None,
            "ema_fast": None,
            "ema_slow": None,
        }
    price = closes[-1]
    e_fast = ema(closes, fast)
    e_slow = ema(closes, slow)
    struct = structure_label(candles)
    stacked_up = bool(e_fast and e_slow and price > e_fast > e_slow)
    stacked_dn = bool(e_fast and e_slow and price < e_fast < e_slow)
    hard_bull = stacked_up and (struct == "HH_HL" if hard_structure else True)
    hard_bear = stacked_dn and (struct == "LH_LL" if hard_structure else True)
    if hard_bull:
        bias = "BULLISH"
    elif hard_bear:
        bias = "BEARISH"
    elif stacked_up:
        bias = "BULLISH"
    elif stacked_dn:
        bias = "BEARISH"
    else:
        bias = "MIXED"
    # Hard = structure + stack (Daily / 4H). Soft lean is not hard.
    is_hard = (hard_bull or hard_bear) if hard_structure else (stacked_up or stacked_dn)
    if hard_structure and stacked_up and struct != "HH_HL":
        is_hard = False
        if struct == "LH_LL":
            bias = "MIXED"
    if hard_structure and stacked_dn and struct != "LH_LL":
        is_hard = False
        if struct == "HH_HL":
            bias = "MIXED"
    return {
        "ok": True,
        "bias": bias,
        "hard": bool(is_hard),
        "structure": struct,
        "price": round(price, 2),
        "ema_fast": round(e_fast, 2) if e_fast else None,
        "ema_slow": round(e_slow, 2) if e_slow else None,
        "stacked_up": stacked_up,
        "stacked_dn": stacked_dn,
    }


def analyze_daily(candles: List[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, Any]:
    bars = closed_candles(candles, 1440, now)
    pack = _frame_bias_ema(bars, fast=20, slow=50, hard_structure=True)
    pack["timeframe"] = "D"
    pack["bars"] = len(bars)
    return pack


def analyze_h4(candles: List[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, Any]:
    bars = closed_candles(candles, 240, now)
    pack = _frame_bias_ema(bars, fast=20, slow=50, hard_structure=True)
    pack["timeframe"] = "240"
    pack["bars"] = len(bars)
    pack["swing_low"] = last_swing_low(bars)
    pack["swing_high"] = last_swing_high(bars)
    return pack


def analyze_h1(candles: List[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    1H turning is not a vibe:
      LONG  — last CLOSED close > 1H 20 EMA AND a higher low
      SHORT — last CLOSED close < 1H 20 EMA AND a lower high
    """
    bars = closed_candles(candles, 60, now)
    closes = [_f(c.get("close")) for c in bars if _f(c.get("close")) > 0]
    if len(closes) < 20:
        return {
            "ok": False,
            "bias": "MIXED",
            "turning": False,
            "turning_side": None,
            "structure": "RANGE",
            "timeframe": "60",
            "bars": len(bars),
            "above_ema20": False,
            "higher_low": False,
            "lower_high": False,
        }
    price = closes[-1]
    e20 = ema(closes, 20)
    struct = structure_label(bars)
    hl = higher_low(bars)
    lh = lower_high(bars)
    above = bool(e20 and price > e20)
    below = bool(e20 and price < e20)
    turning_long = bool(above and hl)
    turning_short = bool(below and lh)
    if above and struct == "HH_HL":
        bias = "BULLISH"
    elif below and struct == "LH_LL":
        bias = "BEARISH"
    elif turning_long:
        bias = "BULLISH"
    elif turning_short:
        bias = "BEARISH"
    elif above:
        bias = "BULLISH"
    elif below:
        bias = "BEARISH"
    else:
        bias = "MIXED"
    # ATR proxy from last 14 1H true ranges
    atr = None
    if len(bars) >= 5:
        trs = []
        for i in range(1, len(bars)):
            h, l, _ = _ohlc(bars[i])
            pc = _f(bars[i - 1].get("close"))
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs[-14:]) / max(len(trs[-14:]), 1)
    mom = momentum_state(bars, atr)
    return {
        "ok": True,
        "timeframe": "60",
        "bias": bias,
        "structure": struct,
        "price": round(price, 2),
        "ema20": round(e20, 2) if e20 else None,
        "above_ema20": above,
        "below_ema20": below,
        "higher_low": hl,
        "lower_high": lh,
        "turning": turning_long or turning_short,
        "turning_side": "BULLISH" if turning_long else "BEARISH" if turning_short else None,
        "momentum_now": mom,
        "atr": round(atr, 4) if atr else None,
        "swing_low": last_swing_low(bars),
        "swing_high": last_swing_high(bars),
        "bars": len(bars),
    }


def analyze_m15(candles: List[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, Any]:
    bars = closed_candles(candles, 15, now)
    closes = [_f(c.get("close")) for c in bars if _f(c.get("close")) > 0]
    if len(closes) < 20:
        return {
            "ok": False,
            "bias": "MIXED",
            "trigger": False,
            "trigger_side": None,
            "timeframe": "15",
            "bars": len(bars),
            "stack": "MIXED",
        }
    price = closes[-1]
    e7 = ema(closes, 7)
    e20 = ema(closes, 20)
    stacked_up = bool(e7 and e20 and price > e7 > e20)
    stacked_dn = bool(e7 and e20 and price < e7 < e20)
    if stacked_up:
        bias, stack = "BULLISH", "BULL"
    elif stacked_dn:
        bias, stack = "BEARISH", "BEAR"
    else:
        bias, stack = "MIXED", "MIXED"
    return {
        "ok": True,
        "timeframe": "15",
        "bias": bias,
        "stack": stack,
        "trigger": stacked_up or stacked_dn,
        "trigger_side": "BULLISH" if stacked_up else "BEARISH" if stacked_dn else None,
        "price": round(price, 2),
        "ema7": round(e7, 2) if e7 else None,
        "ema20": round(e20, 2) if e20 else None,
        "bars": len(bars),
    }


def vote(bias: str) -> int:
    b = (bias or "MIXED").upper()
    if b == "BULLISH":
        return 1
    if b == "BEARISH":
        return -1
    return 0


def fuse_mtf(
    daily: Dict[str, Any],
    h4: Dict[str, Any],
    h1: Dict[str, Any],
    m15: Dict[str, Any],
) -> Dict[str, Any]:
    """
    4H owns allowed_side.
    Daily MIXED is fine.
    Daily HARD opposite of 4H → allowed_side NONE (hard veto).
    """
    d_bias = (daily.get("bias") or "MIXED").upper()
    h4_bias = (h4.get("bias") or "MIXED").upper()
    h1_bias = (h1.get("bias") or "MIXED").upper()
    m15_bias = (m15.get("bias") or "MIXED").upper()
    d_hard = bool(daily.get("hard"))
    h4_hard = bool(h4.get("hard")) or h4_bias in ("BULLISH", "BEARISH")

    daily_veto = False
    if d_hard and h4_bias in ("BULLISH", "BEARISH") and d_bias in ("BULLISH", "BEARISH"):
        if d_bias != h4_bias:
            daily_veto = True

    if daily_veto or not h4.get("ok") or h4_bias not in ("BULLISH", "BEARISH"):
        allowed = "NONE"
    else:
        allowed = "LONG" if h4_bias == "BULLISH" else "SHORT"

    align = vote(d_bias) + vote(h4_bias) + vote(h1_bias) + vote(m15_bias)
    turning = bool(h1.get("turning"))
    turning_side = h1.get("turning_side")
    trigger = bool(m15.get("trigger"))
    trigger_side = m15.get("trigger_side")
    mom = h1.get("momentum_now") or "FLAT"

    # Labels
    if daily_veto:
        label = "DAILY_VETO"
    elif allowed == "NONE":
        label = "MIXED"
    elif allowed == "LONG" and align >= 4 and trigger and trigger_side == "BULLISH":
        label = "FULL_LONG"
    elif allowed == "SHORT" and align <= -4 and trigger and trigger_side == "BEARISH":
        label = "FULL_SHORT"
    elif allowed == "LONG" and align == 2 and turning and turning_side == "BULLISH":
        label = "HQ_PULLBACK_LONG"
    elif allowed == "SHORT" and align == -2 and turning and turning_side == "BEARISH":
        label = "HQ_PULLBACK_SHORT"
    elif allowed == "LONG" and align >= 3:
        label = "WATCH_LONG" if not (trigger and trigger_side == "BULLISH") else "ALIGNED_LONG"
    elif allowed == "SHORT" and align <= -3:
        label = "WATCH_SHORT" if not (trigger and trigger_side == "BEARISH") else "ALIGNED_SHORT"
    elif allowed == "LONG":
        label = "WATCH_LONG"
    elif allowed == "SHORT":
        label = "WATCH_SHORT"
    else:
        label = "MIXED"

    hq_pullback = label in ("HQ_PULLBACK_LONG", "HQ_PULLBACK_SHORT")
    confirmed_ready = label in ("FULL_LONG", "FULL_SHORT", "ALIGNED_LONG", "ALIGNED_SHORT", 
                                "HQ_PULLBACK_LONG", "HQ_PULLBACK_SHORT")
    # FULL / ALIGNED need 15m trigger. HQ pullback is the +2 turning case (best entries).
    if label in ("ALIGNED_LONG", "FULL_LONG"):
        confirmed_ready = trigger and trigger_side == "BULLISH"
    elif label in ("ALIGNED_SHORT", "FULL_SHORT"):
        confirmed_ready = trigger and trigger_side == "BEARISH"
    elif hq_pullback:
        confirmed_ready = True  # turning already proven; 15m trigger still preferred
        if trigger and (
            (label == "HQ_PULLBACK_LONG" and trigger_side != "BULLISH")
            or (label == "HQ_PULLBACK_SHORT" and trigger_side != "BEARISH")
        ):
            confirmed_ready = False

    campaign = (
        "HQ_PULLBACK" if hq_pullback
        else "CONFIRMED" if confirmed_ready and abs(align) >= 3
        else "WATCH"
    )
    if daily_veto or allowed == "NONE":
        campaign = "NO_TRADE"
        confirmed_ready = False

    return {
        "daily_bias": d_bias,
        "daily_hard": d_hard,
        "h4_bias": h4_bias,
        "h4_hard": h4_hard,
        "h1_bias": h1_bias,
        "m15_bias": m15_bias,
        "align_score": align,
        "align_label": label,
        "allowed_side": allowed,
        "daily_veto": daily_veto,
        "hq_pullback": hq_pullback,
        "confirmed_ready": confirmed_ready,
        "campaign": campaign,
        "turning": turning,
        "turning_side": turning_side,
        "m15_trigger": trigger,
        "m15_trigger_side": trigger_side,
        "momentum_now": mom,
        "h1_structure": h1.get("structure"),
        "h4_structure": h4.get("structure"),
        "h1_swing_low": h1.get("swing_low"),
        "h1_swing_high": h1.get("swing_high"),
        "h4_swing_low": h4.get("swing_low"),
        "h4_swing_high": h4.get("swing_high"),
        "frames": {
            "daily": daily,
            "h4": h4,
            "h1": h1,
            "m15": m15,
        },
    }


def mtf_rank(
    align_score: int,
    location_score: float,
    persist_score: float,
    *,
    momentum_now: str = "FLAT",
    hq_pullback: bool = False,
    chain_agree: bool = True,
) -> float:
    """
    Rank so HQ pullbacks are not buried under extended +4 names.
    Compressing full-alignment (already run) is slightly penalised.
    """
    mag = abs(int(align_score))
    mom_mult = 1.15 if momentum_now == "EXPANDING" else 0.72 if momentum_now == "COMPRESSING" else 1.0
    loc = max(float(location_score or 0), 0.0)
    pers = max(float(persist_score or 0), 0.0)
    chain = 1.0 if chain_agree else 0.55
    pull_boost = 1.55 if hq_pullback else 1.0
    return round(mag * mom_mult * (1.0 + loc / 11.0) * (0.5 + pers) * chain * pull_boost, 3)


def frame_invalidation(
    *,
    idea_direction: str,
    mtf: Dict[str, Any],
    h1: Optional[Dict[str, Any]] = None,
    h4: Optional[Dict[str, Any]] = None,
    spot: Optional[float] = None,
) -> Optional[Dict[str, str]]:
    """
    15m never kills.
    1H structure break → downgrade (not kill).
    4H bias / swing break → kill.
    Daily hard flip against the idea → kill (same as 4H campaign death).
    """
    d = (idea_direction or "").upper()
    if d not in ("BULLISH", "BEARISH"):
        return None
    h1 = h1 or (mtf.get("frames") or {}).get("h1") or {}
    h4 = h4 or (mtf.get("frames") or {}).get("h4") or {}

    h4_bias = (mtf.get("h4_bias") or h4.get("bias") or "").upper()
    if h4_bias and h4_bias != "MIXED":
        if d == "BULLISH" and h4_bias == "BEARISH":
            return {"action": "KILL", "frame": "H4", "reason": "4H_BIAS_BREAK"}
        if d == "BEARISH" and h4_bias == "BULLISH":
            return {"action": "KILL", "frame": "H4", "reason": "4H_BIAS_BREAK"}

    if mtf.get("daily_veto"):
        return {"action": "KILL", "frame": "D", "reason": "DAILY_HARD_VETO"}

    # 4H swing break with spot
    if spot is not None:
        if d == "BULLISH" and h4.get("swing_low") and spot < float(h4["swing_low"]):
            return {"action": "KILL", "frame": "H4", "reason": "4H_STRUCTURE_BREAK"}
        if d == "BEARISH" and h4.get("swing_high") and spot > float(h4["swing_high"]):
            return {"action": "KILL", "frame": "H4", "reason": "4H_STRUCTURE_BREAK"}

    # 1H structure break — downgrade
    h1_struct = (h1.get("structure") or mtf.get("h1_structure") or "")
    if d == "BULLISH":
        broke_1h = h1_struct == "LH_LL" or (
            h1.get("swing_low") is not None
            and spot is not None
            and spot < float(h1["swing_low"])
            and not h1.get("above_ema20")
        )
        if broke_1h:
            return {"action": "DOWNGRADE", "frame": "H1", "reason": "1H_STRUCTURE_BREAK"}
    if d == "BEARISH":
        broke_1h = h1_struct == "HH_HL" or (
            h1.get("swing_high") is not None
            and spot is not None
            and spot > float(h1["swing_high"])
            and not h1.get("below_ema20")
        )
        if broke_1h:
            return {"action": "DOWNGRADE", "frame": "H1", "reason": "1H_STRUCTURE_BREAK"}
    return None


def evaluate_mtf(
    *,
    daily_candles: List[Dict[str, Any]],
    h4_candles: List[Dict[str, Any]],
    h1_candles: List[Dict[str, Any]],
    m15_candles: List[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    daily = analyze_daily(daily_candles, now)
    h4 = analyze_h4(h4_candles, now)
    h1 = analyze_h1(h1_candles, now)
    m15 = analyze_m15(m15_candles, now)
    fused = fuse_mtf(daily, h4, h1, m15)
    fused["ok"] = bool(h4.get("ok") or daily.get("ok"))
    return fused
