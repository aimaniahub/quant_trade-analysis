"""
Option-chain snapshots for premium / IV change detection.

Stores a slim ATM-centric snapshot in Redis (or memory fallback) so we can
diff straddle, OTM call premiums, and OI between polls.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_mem: Dict[str, Dict[str, Any]] = {}  # symbol -> {ts, snap}
_MEM_TTL = 3600.0


def _safe(v, default=0.0) -> float:
    try:
        if v is None:
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def build_slim_snapshot(
    chain: List[Dict],
    spot: float,
    atm: Optional[float],
    straddle: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Compact snapshot for Redis (not full chain)."""
    from app.services.option_analytics import _leg, compute_atm_straddle

    if not atm:
        atm = min(
            (r.get("strike_price") for r in chain if r.get("strike_price") is not None),
            key=lambda s: abs(_safe(s) - spot),
            default=None,
        )
    st = straddle or compute_atm_straddle(chain, spot, atm)

    # OTM call ~ +2 steps, OTM put ~ -2 steps
    ordered = sorted(
        [r for r in chain if r.get("strike_price") is not None],
        key=lambda r: _safe(r.get("strike_price")),
    )
    atm_idx = 0
    if atm is not None and ordered:
        atm_idx = min(
            range(len(ordered)),
            key=lambda i: abs(_safe(ordered[i].get("strike_price")) - _safe(atm)),
        )

    def _side_ltp(idx: int, side: str) -> float:
        if idx < 0 or idx >= len(ordered):
            return 0.0
        return _safe(_leg(ordered[idx], side).get("ltp"))

    otm_call = _side_ltp(min(atm_idx + 2, len(ordered) - 1), "call")
    otm_put = _side_ltp(max(atm_idx - 2, 0), "put")
    atm_call = _side_ltp(atm_idx, "call")
    atm_put = _side_ltp(atm_idx, "put")

    total_ce_oi = sum(_safe(_leg(r, "call").get("oi")) for r in ordered)
    total_pe_oi = sum(_safe(_leg(r, "put").get("oi")) for r in ordered)

    return {
        "ts": time.time(),
        "spot": spot,
        "atm": atm,
        "straddle": st.get("straddle"),
        "atm_call": atm_call,
        "atm_put": atm_put,
        "otm_call": otm_call,
        "otm_put": otm_put,
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
    }


def save_snapshot(symbol: str, snap: Dict[str, Any]) -> None:
    if not symbol:
        return
    with _lock:
        _mem[symbol] = {"ts": time.time(), "snap": snap}
        if len(_mem) > 500:
            now = time.time()
            dead = [k for k, v in _mem.items() if now - v["ts"] > _MEM_TTL]
            for k in dead:
                _mem.pop(k, None)
    try:
        from app.services import redis_client as rc
        if rc.is_available():
            rc.set_json(rc.key("ocsnap", symbol), snap, ttl=3600)
    except Exception as e:
        logger.debug("[chain_snapshots] save %s: %s", symbol, e)


def load_previous(symbol: str) -> Optional[Dict[str, Any]]:
    # Prefer Redis
    try:
        from app.services import redis_client as rc
        if rc.is_available():
            raw = rc.get_json(rc.key("ocsnap", symbol))
            if isinstance(raw, dict) and raw.get("ts"):
                return raw
    except Exception:
        pass
    with _lock:
        item = _mem.get(symbol)
        if not item:
            return None
        if time.time() - item["ts"] > _MEM_TTL:
            return None
        return item.get("snap")


def analyze_premium_behaviour(
    chain: List[Dict],
    spot: float,
    atm: Optional[float],
    symbol: Optional[str] = None,
    straddle: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Premium behaviour vs prior snapshot:
    - ATM straddle expanding while spot range-bound → vol expansion risk
    - OTM call accelerating vs ATM → upside reach
    - OTM put collapsing + put OI fall → covering start
    """
    from app.services.option_analytics import compute_atm_straddle

    current = build_slim_snapshot(chain, spot, atm, straddle)
    prev = load_previous(symbol) if symbol else None

    # Always save current for next pass
    if symbol:
        save_snapshot(symbol, current)

    st = straddle or compute_atm_straddle(chain, spot, atm)
    score = 10.0  # base premium readability
    flags: List[str] = []
    bias = "NEUTRAL"
    bull = 0.0
    bear = 0.0

    if not prev or not prev.get("ts"):
        return {
            "ok": True,
            "has_history": False,
            "premium_score": 12.0,
            "bias": "NEUTRAL",
            "flags": ["First snapshot stored — premium deltas next poll"],
            "straddle": st.get("straddle"),
            "expected_move": st.get("expected_move"),
            "squeeze_risk": False,
            "vol_expand_risk": False,
            "current": current,
            "age_sec": None,
        }

    age = time.time() - float(prev.get("ts") or time.time())
    spot_chg_pct = 0.0
    if prev.get("spot"):
        spot_chg_pct = (spot - _safe(prev["spot"])) / max(_safe(prev["spot"]), 1e-9) * 100

    straddle_now = _safe(current.get("straddle"))
    straddle_prev = _safe(prev.get("straddle"))
    straddle_chg_pct = 0.0
    if straddle_prev > 0:
        straddle_chg_pct = (straddle_now - straddle_prev) / straddle_prev * 100

    otm_ce_chg = _safe(current.get("otm_call")) - _safe(prev.get("otm_call"))
    atm_ce_chg = _safe(current.get("atm_call")) - _safe(prev.get("atm_call"))
    otm_pe_chg = _safe(current.get("otm_put")) - _safe(prev.get("otm_put"))
    pe_oi_chg = _safe(current.get("total_pe_oi")) - _safe(prev.get("total_pe_oi"))

    vol_expand = straddle_chg_pct >= 3.0 and abs(spot_chg_pct) < 0.35
    if vol_expand:
        flags.append(
            f"ATM straddle +{straddle_chg_pct:.1f}% while spot ~flat → vol expansion risk"
        )
        score += 8

    # OTM call accelerating vs ATM
    if otm_ce_chg > 0 and (atm_ce_chg <= 0 or otm_ce_chg > atm_ce_chg * 1.15):
        flags.append("OTM call premium accelerating vs ATM (upside reach)")
        bull += 1.25
        score += 6

    # Put premium collapse + put OI fall → covering
    if otm_pe_chg < 0 and pe_oi_chg < 0:
        flags.append("OTM put premium ↓ + put OI ↓ → short covering start")
        bull += 0.75
        score += 4

    # Aggressive call covering (squeeze risk): call OI down + call premium up
    ce_oi_chg = _safe(current.get("total_ce_oi")) - _safe(prev.get("total_ce_oi"))
    squeeze = ce_oi_chg < 0 and atm_ce_chg > 0 and otm_ce_chg >= 0
    if squeeze:
        flags.append("Call writers covering (OI↓ premium↑) — squeeze risk")
        bull += 1.5
        score += 8

    # Bearish premium: OTM put rising faster
    if otm_pe_chg > 0 and otm_pe_chg > abs(otm_ce_chg):
        flags.append("OTM put premium leading — downside hedge bid")
        bear += 1.0
        score += 4

    if bull - bear >= 0.75:
        bias = "BULLISH"
    elif bear - bull >= 0.75:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    score = max(0.0, min(20.0, score))

    return {
        "ok": True,
        "has_history": True,
        "age_sec": round(age, 1),
        "premium_score": round(score, 1),
        "bias": bias,
        "flags": flags[:6],
        "straddle": straddle_now,
        "straddle_chg_pct": round(straddle_chg_pct, 2),
        "spot_chg_pct": round(spot_chg_pct, 3),
        "vol_expand_risk": vol_expand,
        "squeeze_risk": squeeze,
        "otm_call_chg": round(otm_ce_chg, 2),
        "otm_put_chg": round(otm_pe_chg, 2),
        "current": current,
        "note": flags[0] if flags else "Premium structure stable vs last snapshot",
    }
