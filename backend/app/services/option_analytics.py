"""
Deep mathematical option-chain analytics for NSE F&O stocks.

Pure functions over Fyers-normalized chain rows:
  strike_price, call{ltp,oi,volume,iv,delta,gamma,theta,vega,chg}, put{...}

Metrics
-------
• Max Pain (classic OI settlement magnet)
• ATM straddle & 1σ expected move
• PCR (OI / volume)
• IV skew & risk-reversal (OTM put vs OTM call)
• Gamma wall / pin risk
• Delta-weighted OI imbalance
• Premium dislocation (CE/PE equidistant)
• Composite quant_score (0–100) + directional bias
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def _safe(v, default=0.0) -> float:
    try:
        if v is None:
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _leg(row: Dict, side: str) -> Dict:
    return row.get(side) or {}


def compute_max_pain(chain: List[Dict]) -> Dict[str, Any]:
    """
    Max pain: strike that minimizes total option writer payoff at expiry.
    For each candidate strike K:
      pain(K) = Σ call_oi_i * max(K - S_i, 0) + Σ put_oi_j * max(S_j - K, 0)
    """
    if not chain:
        return {"max_pain": None, "pain_by_strike": [], "distance_from_spot": None}

    strikes = [r["strike_price"] for r in chain if r.get("strike_price")]
    if not strikes:
        return {"max_pain": None, "pain_by_strike": [], "distance_from_spot": None}

    pain_list: List[Dict[str, Any]] = []
    for k in strikes:
        pain = 0.0
        for row in chain:
            s = _safe(row.get("strike_price"))
            call_oi = _safe(_leg(row, "call").get("oi"))
            put_oi = _safe(_leg(row, "put").get("oi"))
            # Calls ITM when settlement > strike of that call
            pain += call_oi * max(k - s, 0.0)
            pain += put_oi * max(s - k, 0.0)
        pain_list.append({"strike": k, "pain": pain})

    best = min(pain_list, key=lambda x: x["pain"])
    return {
        "max_pain": best["strike"],
        "pain_value": best["pain"],
        "pain_by_strike": sorted(pain_list, key=lambda x: x["pain"])[:5],
    }


def compute_pcr(chain: List[Dict]) -> Dict[str, Any]:
    total_call_oi = total_put_oi = 0.0
    total_call_vol = total_put_vol = 0.0
    for row in chain:
        c, p = _leg(row, "call"), _leg(row, "put")
        total_call_oi += _safe(c.get("oi"))
        total_put_oi += _safe(p.get("oi"))
        total_call_vol += _safe(c.get("volume"))
        total_put_vol += _safe(p.get("volume"))

    oi_pcr = total_put_oi / max(total_call_oi, 1.0)
    vol_pcr = total_put_vol / max(total_call_vol, 1.0)
    return {
        "oi_pcr": round(oi_pcr, 3),
        "volume_pcr": round(vol_pcr, 3),
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "total_call_volume": total_call_vol,
        "total_put_volume": total_put_vol,
        "oi_bias": (
            "BULLISH" if oi_pcr > 1.1 else "BEARISH" if oi_pcr < 0.8 else "NEUTRAL"
        ),
        "volume_bias": (
            "BULLISH" if vol_pcr > 1.1 else "BEARISH" if vol_pcr < 0.8 else "NEUTRAL"
        ),
    }


def compute_atm_straddle(
    chain: List[Dict], spot: float, atm: Optional[float]
) -> Dict[str, Any]:
    if not atm or not spot:
        return {"straddle": None, "expected_move": None, "expected_move_pct": None}

    row = next((r for r in chain if r.get("strike_price") == atm), None)
    if not row:
        # nearest
        row = min(chain, key=lambda r: abs(_safe(r.get("strike_price")) - spot))
        atm = row.get("strike_price")

    ce = _safe(_leg(row, "call").get("ltp"))
    pe = _safe(_leg(row, "put").get("ltp"))
    straddle = ce + pe
    # Rule-of-thumb: ~68% of straddle ≈ 1σ move for weekly options (market heuristic)
    expected = straddle * 0.85 if straddle > 0 else None
    return {
        "atm_strike": atm,
        "atm_call": ce,
        "atm_put": pe,
        "straddle": round(straddle, 2) if straddle else None,
        "expected_move": round(expected, 2) if expected else None,
        "expected_move_pct": round((expected / spot) * 100, 3) if expected and spot else None,
        "upper_1sd": round(spot + expected, 2) if expected else None,
        "lower_1sd": round(spot - expected, 2) if expected else None,
    }


def _pick_otm(
    chain: List[Dict], spot: float, side: str, moneyness_pct: float = 0.02
) -> Optional[Dict]:
    """
    side='call' → OTM call above spot
    side='put'  → OTM put below spot
    Prefer strike closest to spot*(1±moneyness).
    """
    target = spot * (1 + moneyness_pct) if side == "call" else spot * (1 - moneyness_pct)
    candidates = []
    for row in chain:
        s = _safe(row.get("strike_price"))
        leg = _leg(row, side)
        if not leg:
            continue
        if side == "call" and s > spot:
            candidates.append(row)
        elif side == "put" and s < spot:
            candidates.append(row)
    if not candidates:
        return None
    return min(candidates, key=lambda r: abs(_safe(r.get("strike_price")) - target))


def compute_iv_structure(chain: List[Dict], spot: float, atm: Optional[float]) -> Dict[str, Any]:
    atm_row = None
    if atm:
        atm_row = next((r for r in chain if r.get("strike_price") == atm), None)
    if not atm_row and chain:
        atm_row = min(chain, key=lambda r: abs(_safe(r.get("strike_price")) - spot))

    atm_call_iv = _safe(_leg(atm_row or {}, "call").get("iv")) if atm_row else 0
    atm_put_iv = _safe(_leg(atm_row or {}, "put").get("iv")) if atm_row else 0
    atm_iv = (atm_call_iv + atm_put_iv) / 2 if (atm_call_iv or atm_put_iv) else 0

    otm_call = _pick_otm(chain, spot, "call", 0.02)
    otm_put = _pick_otm(chain, spot, "put", 0.02)
    otm_call_iv = _safe(_leg(otm_call or {}, "call").get("iv")) if otm_call else 0
    otm_put_iv = _safe(_leg(otm_put or {}, "put").get("iv")) if otm_put else 0

    # Skew: positive = puts richer (fear / downside demand)
    skew = otm_put_iv - otm_call_iv if (otm_put_iv or otm_call_iv) else 0
    # Risk reversal: call OTM - put OTM (positive = call demand / bullish)
    risk_reversal = otm_call_iv - otm_put_iv if (otm_call_iv or otm_put_iv) else 0
    # Smile wing: avg OTM IV - ATM IV
    wing = 0.0
    if atm_iv and (otm_call_iv or otm_put_iv):
        wing = ((otm_call_iv + otm_put_iv) / 2) - atm_iv

    skew_label = (
        "PUT_SKEW" if skew > 2 else "CALL_SKEW" if skew < -2 else "FLAT"
    )

    return {
        "atm_iv": round(atm_iv, 2),
        "atm_call_iv": round(atm_call_iv, 2),
        "atm_put_iv": round(atm_put_iv, 2),
        "otm_call_iv": round(otm_call_iv, 2),
        "otm_put_iv": round(otm_put_iv, 2),
        "skew": round(skew, 2),
        "risk_reversal": round(risk_reversal, 2),
        "smile_wing": round(wing, 2),
        "skew_label": skew_label,
        "iv_bias": (
            "BEARISH" if skew > 2 else "BULLISH" if skew < -2 else "NEUTRAL"
        ),
    }


def compute_greeks_walls(chain: List[Dict], spot: float) -> Dict[str, Any]:
    """Gamma wall (max |γ| OI-weighted) and delta-weighted OI net."""
    max_g = -1.0
    max_g_strike = None
    call_delta_oi = 0.0
    put_delta_oi = 0.0
    total_gamma = 0.0

    for row in chain:
        s = _safe(row.get("strike_price"))
        c, p = _leg(row, "call"), _leg(row, "put")
        cg = abs(_safe(c.get("gamma")))
        pg = abs(_safe(p.get("gamma")))
        coi = _safe(c.get("oi"))
        poi = _safe(p.get("oi"))
        g_score = cg * coi + pg * poi
        total_gamma += g_score
        if g_score > max_g:
            max_g = g_score
            max_g_strike = s

        call_delta_oi += _safe(c.get("delta")) * coi
        put_delta_oi += abs(_safe(p.get("delta"))) * poi

    net_delta_oi = call_delta_oi - put_delta_oi
    pin_risk = 0.0
    if max_g_strike and spot and total_gamma > 0:
        # Higher pin when gamma wall is close to spot
        dist_pct = abs(max_g_strike - spot) / spot * 100
        concentration = max_g / total_gamma
        pin_risk = max(0.0, min(100.0, concentration * 100 * (1 - min(dist_pct / 3, 1))))

    return {
        "gamma_wall_strike": max_g_strike,
        "gamma_wall_score": round(max_g, 2),
        "net_delta_oi": round(net_delta_oi, 2),
        "delta_bias": (
            "BULLISH" if net_delta_oi > 0 else "BEARISH" if net_delta_oi < 0 else "NEUTRAL"
        ),
        "pin_risk": round(pin_risk, 1),
        "distance_to_gamma_wall_pct": (
            round(abs(max_g_strike - spot) / spot * 100, 3)
            if max_g_strike and spot
            else None
        ),
    }


def compute_premium_dislocation(
    chain: List[Dict], spot: float, atm: Optional[float]
) -> Dict[str, Any]:
    """
    Equidistant CE/PE premium gaps (Value Adjustment idea).
    For offset k steps from ATM, compare CE(atm+k) vs PE(atm-k).
    """
    if not chain or not atm:
        return {"gaps": [], "best_gap": None}

    by_strike = {r["strike_price"]: r for r in chain if r.get("strike_price") is not None}
    strikes = sorted(by_strike.keys())
    if atm not in by_strike:
        atm = min(strikes, key=lambda s: abs(s - spot))

    # Infer step
    steps = [strikes[i + 1] - strikes[i] for i in range(len(strikes) - 1)]
    step = min(steps) if steps else 50

    gaps = []
    for n in range(1, 6):
        ce_k = atm + n * step
        pe_k = atm - n * step
        if ce_k not in by_strike or pe_k not in by_strike:
            continue
        ce = _safe(_leg(by_strike[ce_k], "call").get("ltp"))
        pe = _safe(_leg(by_strike[pe_k], "put").get("ltp"))
        if ce <= 0 or pe <= 0:
            continue
        gap = abs(ce - pe)
        avg = (ce + pe) / 2
        gaps.append({
            "offset": n * step,
            "call_strike": ce_k,
            "put_strike": pe_k,
            "ce_premium": ce,
            "pe_premium": pe,
            "gap": round(gap, 2),
            "gap_pct": round(gap / avg * 100, 2) if avg else 0,
            "cheap_side": "CE" if ce < pe else "PE",
            "undervalued_strike": ce_k if ce < pe else pe_k,
        })

    best = max(gaps, key=lambda g: g["gap_pct"]) if gaps else None
    return {"gaps": gaps, "best_gap": best, "strike_step": step}


def compute_oi_magnets(chain: List[Dict], spot: float) -> Dict[str, Any]:
    call_levels = []
    put_levels = []
    for row in chain:
        s = _safe(row.get("strike_price"))
        c, p = _leg(row, "call"), _leg(row, "put")
        coi, poi = _safe(c.get("oi")), _safe(p.get("oi"))
        if coi > 0:
            call_levels.append({"strike": s, "oi": coi, "oi_change": _safe(c.get("oi_change"))})
        if poi > 0:
            put_levels.append({"strike": s, "oi": poi, "oi_change": _safe(p.get("oi_change"))})

    call_levels.sort(key=lambda x: x["oi"], reverse=True)
    put_levels.sort(key=lambda x: x["oi"], reverse=True)
    res = call_levels[0] if call_levels else None
    sup = put_levels[0] if put_levels else None

    return {
        "resistance": res["strike"] if res else None,
        "resistance_oi": res["oi"] if res else 0,
        "support": sup["strike"] if sup else None,
        "support_oi": sup["oi"] if sup else 0,
        "top_call_oi": call_levels[:3],
        "top_put_oi": put_levels[:3],
    }


def composite_quant_score(
    pcr: Dict,
    iv: Dict,
    greeks: Dict,
    straddle: Dict,
    max_pain: Dict,
    spot: float,
    institutional_intent: float = 0,
    call_clusters: int = 0,
    put_clusters: int = 0,
) -> Dict[str, Any]:
    """
    Unbiased directional vote + separate edge score.

    Direction = equal-weight votes only (no side gets a permanent head-start).
    quant_score = how readable / actionable the structure is (not "how bearish").
    """
    score = 0.0
    bull = 0.0
    bear = 0.0
    factors: List[str] = []
    votes: List[str] = []  # each independent signal: BULLISH | BEARISH

    # --- Directional votes (symmetric thresholds) ---
    oi_pcr = pcr.get("oi_pcr") or 1.0
    vol_pcr = pcr.get("volume_pcr") or 1.0

    # India F&O convention (symmetric bands):
    # PCR high → put-side OI/volume → often treated as support / bullish cushion
    # PCR low  → call-side heavy → often treated as resistance / bearish
    if oi_pcr >= 1.15:
        votes.append("BULLISH")
        bull += 1
        factors.append(f"OI PCR {oi_pcr:.2f} (put-side support)")
    elif oi_pcr <= 0.85:
        votes.append("BEARISH")
        bear += 1
        factors.append(f"OI PCR {oi_pcr:.2f} (call-side heavy)")

    if vol_pcr >= 1.15:
        votes.append("BULLISH")
        bull += 1
        factors.append(f"Volume PCR {vol_pcr:.2f} (put volume lead)")
    elif vol_pcr <= 0.85:
        votes.append("BEARISH")
        bear += 1
        factors.append(f"Volume PCR {vol_pcr:.2f} (call volume lead)")

    # IV skew: put-rich → defensive/fear (bearish vote); call-rich → bullish vote
    # Same absolute threshold both ways
    skew = float(iv.get("skew") or 0)
    if skew >= 2.0:
        votes.append("BEARISH")
        bear += 1
        factors.append(f"Put IV skew +{skew:.1f}")
    elif skew <= -2.0:
        votes.append("BULLISH")
        bull += 1
        factors.append(f"Call IV skew {skew:.1f}")

    # Delta-weighted OI (symmetric)
    if greeks.get("delta_bias") == "BULLISH":
        votes.append("BULLISH")
        bull += 1
        factors.append("Net delta-OI bullish")
    elif greeks.get("delta_bias") == "BEARISH":
        votes.append("BEARISH")
        bear += 1
        factors.append("Net delta-OI bearish")

    # Flow clusters (equal weight each side)
    if call_clusters > put_clusters:
        votes.append("BULLISH")
        bull += 1
        factors.append(f"Call flow clusters {call_clusters}>{put_clusters}")
    elif put_clusters > call_clusters:
        votes.append("BEARISH")
        bear += 1
        factors.append(f"Put flow clusters {put_clusters}>{call_clusters}")

    # Max pain: spot above pain → mild bullish (writers defend); below → mild bearish
    # Only vote when clearly away from pain (±1%)
    mp = max_pain.get("max_pain")
    if mp and spot:
        dist_pct = (spot - mp) / spot * 100
        if dist_pct >= 1.0:
            votes.append("BULLISH")
            bull += 0.75
            factors.append(f"Spot above max pain ({mp})")
        elif dist_pct <= -1.0:
            votes.append("BEARISH")
            bear += 0.75
            factors.append(f"Spot below max pain ({mp})")

    # --- Edge / readability score (direction-neutral) ---
    # Clarity of structure, not which side is "better"
    if abs(oi_pcr - 1.0) >= 0.15:
        score += 15
    else:
        score += 8

    if abs(skew) >= 2.0:
        score += 12
    else:
        score += 8

    pin = float(greeks.get("pin_risk") or 0)
    score += min(12.0, pin * 0.12)
    if pin > 50:
        factors.append(f"Pin risk {pin:.0f}% @ γ-wall {greeks.get('gamma_wall_strike')}")

    intent = max(0.0, min(100.0, float(institutional_intent or 0)))
    score += intent * 0.18
    if intent >= 50:
        factors.append(f"Flow intensity {intent:.0f}")

    if mp and spot:
        dist = abs(mp - spot) / spot * 100
        score += 12 if dist < 1.0 else 8 if dist < 2.5 else 5

    if straddle.get("expected_move"):
        score += 10
        factors.append(
            f"1σ move ≈ ₹{straddle['expected_move']} ({straddle.get('expected_move_pct')}%)"
        )
    else:
        score += 3

    # Agreement bonus (either side) — rewards consensus, not a direction
    agree = abs(bull - bear)
    if agree >= 2:
        score += 8
    elif agree >= 1:
        score += 4

    score = max(0.0, min(100.0, score))

    # Majority vote with neutral dead-zone (must clear margin)
    if bull - bear >= 1.0:
        bias = "BULLISH"
    elif bear - bull >= 1.0:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    conviction = "HIGH" if score >= 70 and bias != "NEUTRAL" else (
        "MEDIUM" if score >= 50 else "LOW"
    )

    return {
        "quant_score": round(score, 1),
        "bias": bias,
        "conviction": conviction,
        "factors": factors[:8],
        "bull_points": round(bull, 2),
        "bear_points": round(bear, 2),
        "votes": votes,
        "vote_tally": {"bull": round(bull, 2), "bear": round(bear, 2)},
    }


def deep_analyze_chain(
    chain: List[Dict],
    spot: float,
    atm: Optional[float] = None,
    institutional_intent: float = 0,
    symbol: Optional[str] = None,
    call_clusters: int = 0,
    put_clusters: int = 0,
) -> Dict[str, Any]:
    """Full mathematical pack for one option chain."""
    if not chain or not spot or spot <= 0:
        return {"error": "Insufficient chain/spot data"}

    if not atm:
        atm = min(
            (r.get("strike_price") for r in chain if r.get("strike_price") is not None),
            key=lambda s: abs(s - spot),
            default=None,
        )

    pcr = compute_pcr(chain)
    max_pain = compute_max_pain(chain)
    if spot and max_pain.get("max_pain"):
        max_pain["distance_from_spot"] = round(max_pain["max_pain"] - spot, 2)
        max_pain["distance_pct"] = round(
            (max_pain["max_pain"] - spot) / spot * 100, 3
        )

    straddle = compute_atm_straddle(chain, spot, atm)
    iv = compute_iv_structure(chain, spot, atm)
    greeks = compute_greeks_walls(chain, spot)
    dislocation = compute_premium_dislocation(chain, spot, atm)
    magnets = compute_oi_magnets(chain, spot)
    quant = composite_quant_score(
        pcr,
        iv,
        greeks,
        straddle,
        max_pain,
        spot,
        institutional_intent,
        call_clusters=call_clusters,
        put_clusters=put_clusters,
    )

    return {
        "symbol": symbol,
        "spot": spot,
        "atm": atm,
        "pcr": pcr,
        "max_pain": max_pain,
        "straddle": straddle,
        "iv_structure": iv,
        "greeks_walls": greeks,
        "premium_dislocation": dislocation,
        "oi_magnets": magnets,
        "quant": quant,
    }
