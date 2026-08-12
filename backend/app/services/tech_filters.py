"""
Technical stack for option entry filters (desk blueprint §6).

Intraday (15-min):
  - Price vs 7 EMA & 20 EMA
  - Volume vs 20-period average

Higher TF (4H / Daily fallback):
  - Price vs 20 / 50 / 200 EMA bias gate

Results are short-TTL cached (memory + Redis L2 via market history cache)
to avoid double-hitting Fyers on full-universe scans.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_local_lock = threading.Lock()
_local_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_LOCAL_TTL = 90.0  # seconds


def _ema(closes: List[float], period: int) -> Optional[float]:
    if not closes or period <= 0 or len(closes) < period:
        return None
    k = 2.0 / (period + 1)
    # seed with SMA of first `period`
    seed = sum(closes[:period]) / period
    val = seed
    for c in closes[period:]:
        val = c * k + val * (1.0 - k)
    return float(val)


def _closes_volumes(candles: List[Dict]) -> Tuple[List[float], List[float]]:
    closes, vols = [], []
    for c in candles or []:
        try:
            closes.append(float(c.get("close") or 0))
            vols.append(float(c.get("volume") or 0))
        except (TypeError, ValueError):
            continue
    return closes, vols


def analyze_intraday_15m(candles: List[Dict]) -> Dict[str, Any]:
    """15-min 7/20 EMA + volume filter."""
    closes, vols = _closes_volumes(candles)
    if len(closes) < 25:
        return {
            "ok": False,
            "reason": "insufficient_15m_bars",
            "bias": "NEUTRAL",
            "long_ok": False,
            "short_ok": False,
        }

    price = closes[-1]
    ema7 = _ema(closes, 7)
    ema20 = _ema(closes, 20)
    vol = vols[-1] if vols else 0.0
    vol_avg = sum(vols[-21:-1]) / max(len(vols[-21:-1]), 1) if len(vols) >= 21 else (
        sum(vols) / max(len(vols), 1)
    )
    vol_ratio = vol / max(vol_avg, 1.0)

    stacked_up = (
        ema7 is not None
        and ema20 is not None
        and price > ema7 > ema20
    )
    stacked_dn = (
        ema7 is not None
        and ema20 is not None
        and price < ema7 < ema20
    )
    vol_ok = vol_ratio >= 1.0  # at/above average

    # Simple momentum from last 3 closes
    mom = 0.0
    if len(closes) >= 4:
        mom = (closes[-1] - closes[-4]) / max(closes[-4], 1e-9) * 100.0

    if stacked_up:
        bias = "BULLISH"
    elif stacked_dn:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    long_ok = bool(stacked_up and vol_ok)
    short_ok = bool(stacked_dn and vol_ok)

    return {
        "ok": True,
        "timeframe": "15",
        "price": round(price, 2),
        "ema7": round(ema7, 2) if ema7 is not None else None,
        "ema20": round(ema20, 2) if ema20 is not None else None,
        "ema_stack": "BULL" if stacked_up else "BEAR" if stacked_dn else "MIXED",
        "volume": round(vol, 0),
        "volume_avg20": round(vol_avg, 0),
        "volume_ratio": round(vol_ratio, 2),
        "volume_ok": vol_ok,
        "momentum_3bar_pct": round(mom, 3),
        "bias": bias,
        "long_ok": long_ok,
        "short_ok": short_ok,
        "note": (
            "15m stacked above 7>20 EMA + vol"
            if long_ok
            else "15m stacked below 7<20 EMA + vol"
            if short_ok
            else "15m stack/volume not aligned"
        ),
    }


def analyze_htf_bias(candles: List[Dict], label: str = "60") -> Dict[str, Any]:
    """
    Higher-timeframe bias using 20/50/200 EMA.
    Prefer 4H when available; caller may pass 60m (hourly) or D as proxy.
    """
    closes, _ = _closes_volumes(candles)
    need = 200
    if len(closes) < 50:
        return {
            "ok": False,
            "reason": "insufficient_htf_bars",
            "bias": "NEUTRAL",
            "long_ok": False,
            "short_ok": False,
            "timeframe": label,
        }

    price = closes[-1]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ema200 = _ema(closes, 200) if len(closes) >= need else None

    # Full stack when 200 available; else 20/50 only
    if ema200 is not None and ema20 and ema50:
        long_stack = price > ema20 > ema50 > ema200
        short_stack = price < ema20 < ema50 < ema200
        partial = False
    else:
        long_stack = bool(ema20 and ema50 and price > ema20 > ema50)
        short_stack = bool(ema20 and ema50 and price < ema20 < ema50)
        partial = True

    if long_stack:
        bias = "BULLISH"
    elif short_stack:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    return {
        "ok": True,
        "timeframe": label,
        "partial_stack": partial,
        "price": round(price, 2),
        "ema20": round(ema20, 2) if ema20 else None,
        "ema50": round(ema50, 2) if ema50 else None,
        "ema200": round(ema200, 2) if ema200 else None,
        "bias": bias,
        "long_ok": long_stack,
        "short_ok": short_stack,
        "note": (
            f"HTF {label} bull stack 20>50>200"
            if long_stack and not partial
            else f"HTF {label} bear stack 20<50<200"
            if short_stack and not partial
            else f"HTF {label} 20/50 lean {bias}"
            if partial and bias != "NEUTRAL"
            else f"HTF {label} mixed — no hard gate"
        ),
    }


def fuse_technicals(intraday: Dict[str, Any], htf: Dict[str, Any]) -> Dict[str, Any]:
    """Combine 15m + HTF into entry gate + tech score 0–40."""
    id_bias = intraday.get("bias") or "NEUTRAL"
    ht_bias = htf.get("bias") or "NEUTRAL"

    # Hard gate: don't fight HTF when HTF is clear
    long_gate = True
    short_gate = True
    if htf.get("ok") and ht_bias == "BEARISH" and htf.get("short_ok"):
        long_gate = False
    if htf.get("ok") and ht_bias == "BULLISH" and htf.get("long_ok"):
        short_gate = False

    long_signal = bool(intraday.get("long_ok") and long_gate)
    short_signal = bool(intraday.get("short_ok") and short_gate)

    # Tech score 0–40
    score = 10.0
    if intraday.get("ok"):
        score += 8
        if intraday.get("long_ok") or intraday.get("short_ok"):
            score += 10
        if intraday.get("volume_ok"):
            score += 4
    if htf.get("ok"):
        score += 4
        if htf.get("long_ok") or htf.get("short_ok"):
            score += 4

    if long_signal:
        bias = "BULLISH"
    elif short_signal:
        bias = "BEARISH"
    elif id_bias != "NEUTRAL" and (ht_bias == "NEUTRAL" or ht_bias == id_bias):
        bias = id_bias
        score = max(score - 4, 0)
    else:
        bias = "NEUTRAL"

    score = max(0.0, min(40.0, score))

    blocked = None
    if intraday.get("long_ok") and not long_gate:
        blocked = "HTF bearish — long option signals blocked"
    elif intraday.get("short_ok") and not short_gate:
        blocked = "HTF bullish — short option signals blocked"

    return {
        "ok": bool(intraday.get("ok") or htf.get("ok")),
        "bias": bias,
        "tech_score": round(score, 1),
        "long_signal": long_signal,
        "short_signal": short_signal,
        "long_gate": long_gate,
        "short_gate": short_gate,
        "blocked_reason": blocked,
        "intraday": intraday,
        "htf": htf,
        "aligned": id_bias == ht_bias and id_bias != "NEUTRAL",
        "note": blocked
        or (
            "15m+HTF aligned long"
            if long_signal
            else "15m+HTF aligned short"
            if short_signal
            else "Technical stack mixed / wait"
        ),
    }


def get_technical_context(symbol: str, force: bool = False) -> Dict[str, Any]:
    """
    Fetch 15m + hourly history and build fused technical context.
    Skips cleanly on rate-limit / missing data.
    """
    now = time.time()
    cache_key = f"tech:{symbol}"
    if not force:
        with _local_lock:
            hit = _local_cache.get(cache_key)
            if hit and hit[0] > now:
                return {**hit[1], "cached": True}

    try:
        from app.services.rate_limiter import get_fyers_limiter
        lim = get_fyers_limiter()
        if lim.in_cooldown:
            return {
                "ok": False,
                "reason": "rate_limited",
                "bias": "NEUTRAL",
                "tech_score": 0,
                "long_signal": False,
                "short_signal": False,
            }
    except Exception:
        pass

    try:
        from app.services.fyers_market import get_market_service

        mkt = get_market_service()
        # 15-min: primary intraday stack (one REST call, cached)
        h15 = mkt.get_historical_data(symbol, resolution="15", days=8)
        c15 = h15.get("candles") if h15.get("success") else []
        intraday = analyze_intraday_15m(c15 or [])

        # HTF: prefer Redis warm cache; else one hourly pull if not cooling down
        htf = {
            "ok": False,
            "bias": "NEUTRAL",
            "long_ok": False,
            "short_ok": False,
            "timeframe": "60m~4H",
            "reason": "skipped",
        }
        try:
            from app.services import redis_client as rc
            if rc.is_available():
                warm = rc.get_json(rc.key("tech_htf", symbol))
                if isinstance(warm, dict) and warm.get("ok"):
                    htf = warm
        except Exception:
            pass

        if not htf.get("ok"):
            try:
                lim2 = get_fyers_limiter()
                if not lim2.in_cooldown:
                    h60 = mkt.get_historical_data(symbol, resolution="60", days=120)
                    c60 = h60.get("candles") if h60.get("success") else []
                    if c60 and len(c60) >= 50:
                        htf = analyze_htf_bias(c60, label="60m~4H")
                    else:
                        h_d = mkt.get_historical_data(symbol, resolution="D", days=280)
                        cd = h_d.get("candles") if h_d.get("success") else []
                        htf = analyze_htf_bias(cd or [], label="D")
                    try:
                        if rc.is_available() and htf.get("ok"):
                            rc.set_json(rc.key("tech_htf", symbol), htf, ttl=300)
                    except Exception:
                        pass
            except Exception:
                pass

        fused = fuse_technicals(intraday, htf)
        fused["ok"] = bool(intraday.get("ok") or htf.get("ok"))
        fused["symbol"] = symbol
        fused["cached"] = False

        with _local_lock:
            _local_cache[cache_key] = (now + _LOCAL_TTL, fused)
            # cap
            if len(_local_cache) > 400:
                dead = [k for k, (exp, _) in _local_cache.items() if exp <= now]
                for k in dead:
                    _local_cache.pop(k, None)

        # Optional Redis mirror for multi-worker
        try:
            from app.services import redis_client as rc
            if rc.is_available():
                rc.set_json(rc.key("tech", symbol), fused, ttl=int(_LOCAL_TTL))
        except Exception:
            pass

        return fused
    except Exception as e:
        logger.debug("[tech_filters] %s: %s", symbol, e)
        return {
            "ok": False,
            "reason": str(e),
            "bias": "NEUTRAL",
            "tech_score": 0,
            "long_signal": False,
            "short_signal": False,
            "symbol": symbol,
        }
