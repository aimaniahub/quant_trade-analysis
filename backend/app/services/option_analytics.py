"""
Deep mathematical option-chain analytics for NSE F&O stocks.

Pure functions over Fyers-normalized chain rows:
  strike_price, call{ltp,oi,volume,iv,delta,gamma,theta,vega,chg,oi_change}, put{...}

Metrics
-------
• Four canonical OI buildups (Long/Short Buildup, Short Covering, Long Unwinding)
• Professional PCR suite (OI / Volume / ATM / band) + regime tags
• Max Pain, call/put walls, gamma pin
• ATM straddle & 1σ expected move
• IV skew & risk-reversal
• Premium dislocation
• Composite quant_score (0–100) + directional bias (buildup-aware)
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Optional, Tuple


# ── Buildup thresholds (tunable) ──────────────────────────────────
VOR_ACTIVE = 0.35          # Volume / OI — active trading
DOI_MEANINGFUL_PCT = 5.0   # |ΔOI| % of prior OI
VOL_STRONG_MULT = 1.5      # vs chain median volume for Strong

BUILDUP_LONG = "Long Buildup"
BUILDUP_SHORT = "Short Buildup"
BUILDUP_SC = "Short Covering"
BUILDUP_LU = "Long Unwinding"
BUILDUP_NEUTRAL = "Churn / Neutral"


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
    """Backward-compatible PCR + extended professional fields. """
    return compute_professional_pcr(chain, spot=None, atm=None, band=5)


def classify_buildup(
    price_change: float,
    oi_change: float,
    volume: float = 0.0,
    avg_volume: float = 0.0,
    prev_oi: float = 0.0,
    oi: float = 0.0,
) -> Dict[str, Any]:
    """
    Four canonical states (desk standard):

    Price↑ + OI↑ → Long Buildup
    Price↓ + OI↑ → Short Buildup
    Price↑ + OI↓ → Short Covering
    Price↓ + OI↓ → Long Unwinding
    """
    pc = _safe(price_change)
    oc = _safe(oi_change)
    vol = _safe(volume)
    avg_vol = _safe(avg_volume)
    base_oi = _safe(prev_oi)
    if base_oi <= 0:
        # Reconstruct prior OI when only current OI + change known
        base_oi = max(_safe(oi) - oc, 0.0)

    vor = vol / max(_safe(oi), 1.0)
    doi_pct = abs(oc) / max(base_oi, 1.0) * 100.0 if (base_oi > 0 or abs(oc) > 0) else 0.0
    meaningful = doi_pct >= DOI_MEANINGFUL_PCT or abs(oc) >= 50_000  # loose floor for liquid names
    active = vor >= VOR_ACTIVE or vol >= max(avg_vol, 1.0) * 0.5

    # Tiny moves → churn
    if abs(pc) < 1e-9 and abs(oc) < 1e-9:
        state, strength = BUILDUP_NEUTRAL, "None"
    elif pc > 0 and oc > 0:
        state = BUILDUP_LONG
        strength = "Strong" if (vol >= VOL_STRONG_MULT * max(avg_vol, 1.0) and meaningful) else (
            "Weak" if meaningful or active else "Weak"
        )
        if not meaningful and vol < max(avg_vol, 1.0):
            strength = "Weak"
    elif pc < 0 and oc > 0:
        state = BUILDUP_SHORT
        strength = "Strong" if (vol >= VOL_STRONG_MULT * max(avg_vol, 1.0) and meaningful) else "Weak"
    elif pc > 0 and oc < 0:
        state, strength = BUILDUP_SC, "Moderate"
    elif pc < 0 and oc < 0:
        state, strength = BUILDUP_LU, "Moderate"
    else:
        state, strength = BUILDUP_NEUTRAL, "None"

    # Premium confirmation: long buildup stronger if premium rising already in pc
    premium_confirm = False
    if state == BUILDUP_LONG and pc > 0:
        premium_confirm = True
    elif state == BUILDUP_SHORT and pc < 0:
        premium_confirm = True

    actionable = state in (BUILDUP_LONG, BUILDUP_SHORT) and strength == "Strong"
    fade_risk = state == BUILDUP_SC  # rally may die once covering done

    return {
        "state": state,
        "strength": strength,
        "price_change": round(pc, 4),
        "oi_change": round(oc, 2),
        "doi_pct": round(doi_pct, 2),
        "vor": round(vor, 4),
        "volume": round(vol, 2),
        "avg_volume": round(avg_vol, 2),
        "meaningful_doi": meaningful,
        "active_vor": active,
        "premium_confirm": premium_confirm,
        "actionable": actionable,
        "fade_risk": fade_risk,
    }


def _chain_median_volume(chain: List[Dict], side: str) -> float:
    vols = []
    for row in chain:
        v = _safe(_leg(row, side).get("volume"))
        if v > 0:
            vols.append(v)
    if not vols:
        return 1.0
    try:
        return float(statistics.median(vols))
    except Exception:
        return float(sum(vols) / len(vols))


def _leg_price_change(leg: Dict) -> float:
    """Prefer absolute LTP change; fall back to % so zeros don't kill classification."""
    chg = _safe(leg.get("chg"))
    if abs(chg) > 1e-9:
        return chg
    return _safe(leg.get("chg_pct"))


def analyze_chain_buildups(
    chain: List[Dict],
    spot: float,
    atm: Optional[float] = None,
    band: int = 3,
) -> Dict[str, Any]:
    """
    Per-strike CE/PE buildup + ATM-band rollup used for bias and UI.
    Uses option premium direction (chg) + ΔOI — desk-style for stock options.
    """
    if not chain:
        return {"error": "no chain", "strikes": [], "summary": {}}

    if not atm:
        atm = min(
            (r.get("strike_price") for r in chain if r.get("strike_price") is not None),
            key=lambda s: abs(_safe(s) - spot),
            default=None,
        )

    med_ce = _chain_median_volume(chain, "call")
    med_pe = _chain_median_volume(chain, "put")

    strikes_out: List[Dict[str, Any]] = []
    counts = {
        BUILDUP_LONG: 0,
        BUILDUP_SHORT: 0,
        BUILDUP_SC: 0,
        BUILDUP_LU: 0,
        BUILDUP_NEUTRAL: 0,
    }
    strong_long_ce = 0
    strong_short_pe = 0
    strong_long_pe = 0  # put long buildup = bearish
    strong_short_ce = 0  # call short buildup = bearish
    sc_calls = 0
    sc_puts = 0

    # Sort strikes for band selection
    ordered = sorted(
        [r for r in chain if r.get("strike_price") is not None],
        key=lambda r: _safe(r.get("strike_price")),
    )
    atm_idx = 0
    if atm is not None:
        atm_idx = min(
            range(len(ordered)),
            key=lambda i: abs(_safe(ordered[i].get("strike_price")) - _safe(atm)),
            default=0,
        )
    lo = max(0, atm_idx - band)
    hi = min(len(ordered), atm_idx + band + 1)
    band_set = set(id(ordered[i]) for i in range(lo, hi))

    atm_band_rows: List[Dict[str, Any]] = []

    for row in ordered:
        s = _safe(row.get("strike_price"))
        c, p = _leg(row, "call"), _leg(row, "put")
        ce_b = classify_buildup(
            _leg_price_change(c),
            _safe(c.get("oi_change")),
            _safe(c.get("volume")),
            med_ce,
            _safe(c.get("prev_oi")),
            _safe(c.get("oi")),
        )
        pe_b = classify_buildup(
            _leg_price_change(p),
            _safe(p.get("oi_change")),
            _safe(p.get("volume")),
            med_pe,
            _safe(p.get("prev_oi")),
            _safe(p.get("oi")),
        )
        counts[ce_b["state"]] = counts.get(ce_b["state"], 0) + 1
        counts[pe_b["state"]] = counts.get(pe_b["state"], 0) + 1

        if ce_b["state"] == BUILDUP_LONG and ce_b["strength"] == "Strong":
            strong_long_ce += 1
        if ce_b["state"] == BUILDUP_SHORT and ce_b["strength"] == "Strong":
            strong_short_ce += 1
        if pe_b["state"] == BUILDUP_LONG and pe_b["strength"] == "Strong":
            strong_long_pe += 1
        if pe_b["state"] == BUILDUP_SHORT and pe_b["strength"] == "Strong":
            strong_short_pe += 1
        if ce_b["state"] == BUILDUP_SC:
            sc_calls += 1
        if pe_b["state"] == BUILDUP_SC:
            sc_puts += 1

        entry = {
            "strike": s,
            "is_atm": abs(s - _safe(atm)) < 1e-6 if atm else False,
            "in_band": id(row) in band_set,
            "call": {**ce_b, "oi": _safe(c.get("oi")), "ltp": _safe(c.get("ltp"))},
            "put": {**pe_b, "oi": _safe(p.get("oi")), "ltp": _safe(p.get("ltp"))},
        }
        strikes_out.append(entry)
        if id(row) in band_set:
            atm_band_rows.append(entry)

    # Dominant narrative for ATM ± band
    band_long_ce = sum(
        1 for e in atm_band_rows if e["call"]["state"] == BUILDUP_LONG
    )
    band_short_pe = sum(
        1 for e in atm_band_rows if e["put"]["state"] == BUILDUP_SHORT
    )
    band_sc_ce = sum(1 for e in atm_band_rows if e["call"]["state"] == BUILDUP_SC)
    band_long_pe = sum(
        1 for e in atm_band_rows if e["put"]["state"] == BUILDUP_LONG
    )
    band_short_ce = sum(
        1 for e in atm_band_rows if e["call"]["state"] == BUILDUP_SHORT
    )

    # Bias from buildup (not absolute OI)
    bull_pts = strong_long_ce * 2 + band_long_ce + strong_short_pe + band_short_pe * 0.5
    bear_pts = strong_long_pe * 2 + band_long_pe + strong_short_ce + band_short_ce * 0.5
    # Short covering rally = weaker bull (fade risk)
    if band_sc_ce > band_long_ce and bull_pts >= bear_pts:
        primary = BUILDUP_SC
        bias = "BULLISH"
        conviction = "LOW"
        note = "ATM rally leans Short Covering — may fade once covering done"
    elif bull_pts - bear_pts >= 1.5:
        primary = BUILDUP_LONG
        bias = "BULLISH"
        conviction = "HIGH" if strong_long_ce >= 1 else "MEDIUM"
        note = "Call Long Buildup / Put Short Covering tilt — fresher bullish money"
    elif bear_pts - bull_pts >= 1.5:
        primary = BUILDUP_SHORT if strong_short_ce or band_short_ce else BUILDUP_LONG
        # Put long buildup is bearish
        if strong_long_pe or band_long_pe >= band_short_ce:
            primary = BUILDUP_LONG  # on puts
            note = "Put Long Buildup / Call Short Buildup — fresh bearish money"
        else:
            note = "Call Short Buildup dominant — fresh bearish writers"
        bias = "BEARISH"
        conviction = "HIGH" if (strong_long_pe + strong_short_ce) >= 1 else "MEDIUM"
    else:
        primary = BUILDUP_NEUTRAL
        bias = "NEUTRAL"
        conviction = "LOW"
        note = "Mixed buildup / churn near ATM"

    # Top actionable strikes for UI chips
    actionable: List[Dict[str, Any]] = []
    for e in strikes_out:
        for side, key in (("CE", "call"), ("PE", "put")):
            b = e[key]
            if b.get("actionable") or (
                b.get("state") in (BUILDUP_LONG, BUILDUP_SHORT)
                and b.get("strength") in ("Strong", "Moderate")
                and e.get("in_band")
            ):
                actionable.append(
                    {
                        "strike": e["strike"],
                        "side": side,
                        "state": b["state"],
                        "strength": b["strength"],
                        "oi_change": b["oi_change"],
                        "fade_risk": b.get("fade_risk"),
                    }
                )
    actionable.sort(
        key=lambda x: (
            0 if x["strength"] == "Strong" else 1,
            -abs(_safe(x.get("oi_change"))),
        )
    )

    return {
        "atm": atm,
        "band": band,
        "median_call_volume": round(med_ce, 1),
        "median_put_volume": round(med_pe, 1),
        "counts": counts,
        "strong_long_ce": strong_long_ce,
        "strong_short_ce": strong_short_ce,
        "strong_long_pe": strong_long_pe,
        "strong_short_pe": strong_short_pe,
        "short_covering_calls": sc_calls,
        "short_covering_puts": sc_puts,
        "primary_state": primary,
        "bias": bias,
        "conviction": conviction,
        "note": note,
        "bull_points": round(bull_pts, 2),
        "bear_points": round(bear_pts, 2),
        "atm_band": atm_band_rows,
        "actionable": actionable[:12],
        "strikes": strikes_out,  # full chain classification
    }


def compute_professional_pcr(
    chain: List[Dict],
    spot: Optional[float] = None,
    atm: Optional[float] = None,
    band: int = 5,
) -> Dict[str, Any]:
    """
    OI PCR + Volume PCR + ATM PCR + ±band PCR + India regime labels.
    """
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

    if not atm and spot and chain:
        atm = min(
            (r.get("strike_price") for r in chain if r.get("strike_price") is not None),
            key=lambda s: abs(_safe(s) - spot),
            default=None,
        )

    atm_call_oi = atm_put_oi = atm_call_vol = atm_put_vol = 0.0
    band_call_oi = band_put_oi = band_call_vol = band_put_vol = 0.0

    if atm is not None:
        ordered = sorted(
            [r for r in chain if r.get("strike_price") is not None],
            key=lambda r: _safe(r.get("strike_price")),
        )
        atm_idx = min(
            range(len(ordered)),
            key=lambda i: abs(_safe(ordered[i].get("strike_price")) - _safe(atm)),
            default=0,
        )
        lo, hi = max(0, atm_idx - band), min(len(ordered), atm_idx + band + 1)
        for i, row in enumerate(ordered):
            c, p = _leg(row, "call"), _leg(row, "put")
            if i == atm_idx:
                atm_call_oi = _safe(c.get("oi"))
                atm_put_oi = _safe(p.get("oi"))
                atm_call_vol = _safe(c.get("volume"))
                atm_put_vol = _safe(p.get("volume"))
            if lo <= i < hi:
                band_call_oi += _safe(c.get("oi"))
                band_put_oi += _safe(p.get("oi"))
                band_call_vol += _safe(c.get("volume"))
                band_put_vol += _safe(p.get("volume"))

    atm_oi_pcr = atm_put_oi / max(atm_call_oi, 1.0)
    atm_vol_pcr = atm_put_vol / max(atm_call_vol, 1.0)
    band_oi_pcr = band_put_oi / max(band_call_oi, 1.0)
    band_vol_pcr = band_put_vol / max(band_call_vol, 1.0)

    # Structural labels (India)
    if oi_pcr >= 1.25:
        regime = "PUT_WRITING_FLOOR"
        regime_label = "Strong put writing → bullish floor"
        oi_bias = "BULLISH"
    elif oi_pcr <= 0.7:
        regime = "CALL_WRITING_CEILING"
        regime_label = "Aggressive call writing → bearish ceiling"
        oi_bias = "BEARISH"
    elif oi_pcr >= 1.1:
        regime = "PUT_LEAN"
        regime_label = "Mild put-side support"
        oi_bias = "BULLISH"
    elif oi_pcr <= 0.85:
        regime = "CALL_LEAN"
        regime_label = "Mild call-side pressure"
        oi_bias = "BEARISH"
    else:
        regime = "BALANCED"
        regime_label = "Balanced PCR"
        oi_bias = "NEUTRAL"

    vol_bias = (
        "BULLISH" if vol_pcr > 1.1 else "BEARISH" if vol_pcr < 0.8 else "NEUTRAL"
    )

    # Rising PCR + rising price would need history — flag ATM vs total divergence
    health = "NEUTRAL"
    if oi_pcr >= 1.15 and vol_pcr >= 1.05:
        health = "HEALTHY_BULLISH_SUPPORT"
    elif oi_pcr <= 0.85 and vol_pcr <= 0.95:
        health = "BEARISH_CEILING_ACTIVE"
    elif vol_pcr < oi_pcr - 0.25 and oi_pcr > 1.0:
        health = "POSSIBLE_SHORT_COVERING_NOISE"

    total_opt_vol = total_call_vol + total_put_vol
    ce_vol_share = total_call_vol / max(total_opt_vol, 1.0)
    pe_vol_share = total_put_vol / max(total_opt_vol, 1.0)
    band_opt_vol = band_call_vol + band_put_vol
    atm_opt_vol = atm_call_vol + atm_put_vol
    # CE-heavy options activity near ATM (bullish participation)
    atm_ce_vol_share = atm_call_vol / max(atm_opt_vol, 1.0)
    band_ce_vol_share = band_call_vol / max(band_opt_vol, 1.0)

    # Relative option activity vs chain median (proxy when multi-day avg unavailable)
    all_vols = []
    for row in chain:
        all_vols.append(_safe(_leg(row, "call").get("volume")))
        all_vols.append(_safe(_leg(row, "put").get("volume")))
    pos_vols = [v for v in all_vols if v > 0]
    med_leg_vol = float(statistics.median(pos_vols)) if pos_vols else 1.0
    atm_ce_rel = atm_call_vol / max(med_leg_vol, 1.0)
    atm_pe_rel = atm_put_vol / max(med_leg_vol, 1.0)

    return {
        "oi_pcr": round(oi_pcr, 3),
        "volume_pcr": round(vol_pcr, 3),
        "atm_oi_pcr": round(atm_oi_pcr, 3),
        "atm_volume_pcr": round(atm_vol_pcr, 3),
        "band_oi_pcr": round(band_oi_pcr, 3),
        "band_volume_pcr": round(band_vol_pcr, 3),
        "band": band,
        "atm": atm,
        "total_call_oi": total_call_oi,
        "total_put_oi": total_put_oi,
        "total_call_volume": total_call_vol,
        "total_put_volume": total_put_vol,
        "ce_vol_share": round(ce_vol_share, 3),
        "pe_vol_share": round(pe_vol_share, 3),
        "atm_call_volume": atm_call_vol,
        "atm_put_volume": atm_put_vol,
        "band_call_volume": band_call_vol,
        "band_put_volume": band_put_vol,
        "atm_ce_vol_share": round(atm_ce_vol_share, 3),
        "band_ce_vol_share": round(band_ce_vol_share, 3),
        "atm_ce_rel_vol": round(atm_ce_rel, 2),
        "atm_pe_rel_vol": round(atm_pe_rel, 2),
        "median_leg_volume": round(med_leg_vol, 1),
        "oi_bias": oi_bias,
        "volume_bias": vol_bias,
        "regime": regime,
        "regime_label": regime_label,
        "health": health,
    }


def compute_structure_walls(chain: List[Dict], spot: float) -> Dict[str, Any]:
    """
    Call wall (resistance) = highest Call OI above/near spot
    Put wall (support) = highest Put OI below/near spot
    Plus max-pain-adjacent magnets.
    """
    magnets = compute_oi_magnets(chain, spot)
    call_wall = magnets.get("resistance")
    put_wall = magnets.get("support")
    return {
        "call_wall": call_wall,
        "call_wall_oi": magnets.get("resistance_oi"),
        "put_wall": put_wall,
        "put_wall_oi": magnets.get("support_oi"),
        "top_call_oi": magnets.get("top_call_oi") or [],
        "top_put_oi": magnets.get("top_put_oi") or [],
        "support": put_wall,
        "resistance": call_wall,
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
    buildup: Optional[Dict] = None,
    walls: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Unbiased directional vote + edge score.
    Buildup classification is first-class (stronger weight than absolute OI).
    """
    score = 0.0
    bull = 0.0
    bear = 0.0
    factors: List[str] = []
    votes: List[str] = []

    buildup = buildup or {}
    walls = walls or {}

    # --- 1) Buildup engine (highest weight) ---
    b_bias = buildup.get("bias")
    b_state = buildup.get("primary_state") or BUILDUP_NEUTRAL
    b_conv = buildup.get("conviction") or "LOW"
    if b_bias == "BULLISH":
        w = 2.0 if b_conv == "HIGH" else 1.25
        votes.append("BULLISH")
        bull += w
        factors.append(f"{b_state} ({b_conv}) — {buildup.get('note', 'buildup')[:60]}")
        if b_state == BUILDUP_SC:
            # Fade risk: keep vote but cut conviction later
            factors.append("Short Covering tilt — rally may fade")
    elif b_bias == "BEARISH":
        w = 2.0 if b_conv == "HIGH" else 1.25
        votes.append("BEARISH")
        bear += w
        factors.append(f"{b_state} ({b_conv}) — {buildup.get('note', 'buildup')[:60]}")

    strong_ce = int(buildup.get("strong_long_ce") or 0)
    strong_pe = int(buildup.get("strong_long_pe") or 0)
    if strong_ce:
        factors.append(f"Strong CE Long Buildup ×{strong_ce}")
    if strong_pe:
        factors.append(f"Strong PE Long Buildup ×{strong_pe}")

    # --- 2) PCR suite ---
    oi_pcr = pcr.get("oi_pcr") or 1.0
    vol_pcr = pcr.get("volume_pcr") or 1.0
    atm_pcr = pcr.get("atm_oi_pcr")

    if oi_pcr >= 1.2:
        votes.append("BULLISH")
        bull += 1
        factors.append(f"OI PCR {oi_pcr:.2f} put-writing floor")
    elif oi_pcr <= 0.75:
        votes.append("BEARISH")
        bear += 1
        factors.append(f"OI PCR {oi_pcr:.2f} call-writing ceiling")

    if vol_pcr >= 1.15:
        votes.append("BULLISH")
        bull += 0.75
        factors.append(f"Vol PCR {vol_pcr:.2f}")
    elif vol_pcr <= 0.85:
        votes.append("BEARISH")
        bear += 0.75
        factors.append(f"Vol PCR {vol_pcr:.2f}")

    if atm_pcr is not None:
        if atm_pcr >= 1.2:
            votes.append("BULLISH")
            bull += 0.5
            factors.append(f"ATM PCR {atm_pcr:.2f}")
        elif atm_pcr <= 0.8:
            votes.append("BEARISH")
            bear += 0.5
            factors.append(f"ATM PCR {atm_pcr:.2f}")

    if pcr.get("regime_label"):
        factors.append(str(pcr["regime_label"])[:50])

    # --- 3) IV skew ---
    skew = float(iv.get("skew") or 0)
    if skew >= 2.0:
        votes.append("BEARISH")
        bear += 1
        factors.append(f"Put IV skew +{skew:.1f}")
    elif skew <= -2.0:
        votes.append("BULLISH")
        bull += 1
        factors.append(f"Call IV skew {skew:.1f}")

    # --- 4) Delta-OI ---
    if greeks.get("delta_bias") == "BULLISH":
        votes.append("BULLISH")
        bull += 1
        factors.append("Net delta-OI bullish")
    elif greeks.get("delta_bias") == "BEARISH":
        votes.append("BEARISH")
        bear += 1
        factors.append("Net delta-OI bearish")

    # --- 5) Flow clusters ---
    if call_clusters > put_clusters:
        votes.append("BULLISH")
        bull += 0.75
        factors.append(f"Call clusters {call_clusters}>{put_clusters}")
    elif put_clusters > call_clusters:
        votes.append("BEARISH")
        bear += 0.75
        factors.append(f"Put clusters {put_clusters}>{call_clusters}")

    # --- 6) Max pain ---
    mp = max_pain.get("max_pain")
    if mp and spot:
        dist_pct = (spot - mp) / spot * 100
        if dist_pct >= 1.0:
            votes.append("BULLISH")
            bull += 0.5
            factors.append(f"Spot above max pain ({mp})")
        elif dist_pct <= -1.0:
            votes.append("BEARISH")
            bear += 0.5
            factors.append(f"Spot below max pain ({mp})")

    # --- Edge score ---
    if abs(oi_pcr - 1.0) >= 0.15:
        score += 12
    else:
        score += 6

    if buildup.get("primary_state") and buildup.get("primary_state") != BUILDUP_NEUTRAL:
        score += 14 if b_conv == "HIGH" else 10
    else:
        score += 4

    if abs(skew) >= 2.0:
        score += 10
    else:
        score += 6

    pin = float(greeks.get("pin_risk") or 0)
    score += min(10.0, pin * 0.1)
    if pin > 50:
        factors.append(f"Pin risk {pin:.0f}% @ γ-wall {greeks.get('gamma_wall_strike')}")

    intent = max(0.0, min(100.0, float(institutional_intent or 0)))
    score += intent * 0.15

    if mp and spot:
        dist = abs(mp - spot) / spot * 100
        score += 10 if dist < 1.0 else 6 if dist < 2.5 else 4

    if straddle.get("expected_move"):
        score += 8
        factors.append(
            f"1σ ≈ ₹{straddle['expected_move']} ({straddle.get('expected_move_pct')}%)"
        )

    if walls.get("call_wall") or walls.get("put_wall"):
        score += 6
        factors.append(
            f"Walls P{walls.get('put_wall')}/C{walls.get('call_wall')}"
        )

    agree = abs(bull - bear)
    if agree >= 2:
        score += 8
    elif agree >= 1:
        score += 4

    # Penalize short-covering-only narratives
    if b_state == BUILDUP_SC and b_bias == "BULLISH":
        score = max(0.0, score - 8)
        bull = max(0.0, bull - 0.5)

    score = max(0.0, min(100.0, score))

    if bull - bear >= 1.25:
        bias = "BULLISH"
    elif bear - bull >= 1.25:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    conviction = (
        "HIGH"
        if score >= 70 and bias != "NEUTRAL" and b_state != BUILDUP_SC
        else "MEDIUM"
        if score >= 50
        else "LOW"
    )
    if b_state == BUILDUP_SC and bias == "BULLISH":
        conviction = "LOW"

    return {
        "quant_score": round(score, 1),
        "bias": bias,
        "conviction": conviction,
        "factors": factors[:10],
        "bull_points": round(bull, 2),
        "bear_points": round(bear, 2),
        "votes": votes,
        "vote_tally": {"bull": round(bull, 2), "bear": round(bear, 2)},
        "primary_buildup": b_state,
        "buildup_note": buildup.get("note"),
        # component scores for desk stack (option-only until fused)
        "option_score": round(min(40.0, score * 0.4), 1),
    }


def fuse_desk_conviction(
    quant: Dict[str, Any],
    buildup: Optional[Dict] = None,
    tech: Optional[Dict] = None,
    premium: Optional[Dict] = None,
    *,
    pcr: Optional[Dict] = None,
    greeks: Optional[Dict] = None,
    max_pain: Optional[Dict] = None,
    iv: Optional[Dict] = None,
    spot: float = 0.0,
) -> Dict[str, Any]:
    """
    Hardened desk decision (Option_Chain_Analyzer_Fix_Report.md).

    Priority: HTF gate → PCR structure → Buildup → Gamma/MaxPain → Skew/Premium → 15m.
    Conflicting flow vs structure defaults to WAIT — never aggressive BUY.
    """
    from app.services.desk_decision import fuse_with_hardened_decision

    return fuse_with_hardened_decision(
        quant,
        buildup,
        tech,
        premium,
        pcr=pcr,
        greeks=greeks,
        max_pain=max_pain,
        iv=iv,
        spot=spot,
    )


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

    pcr = compute_professional_pcr(chain, spot=spot, atm=atm, band=5)
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
    walls = compute_structure_walls(chain, spot)
    # Per-strike + ATM-band buildup (four canonical states)
    buildup_full = analyze_chain_buildups(chain, spot, atm, band=3)
    # Slim payload for list UIs (drop full strikes to save bandwidth)
    buildup_summary = {
        k: buildup_full.get(k)
        for k in (
            "atm",
            "band",
            "primary_state",
            "bias",
            "conviction",
            "note",
            "bull_points",
            "bear_points",
            "strong_long_ce",
            "strong_short_ce",
            "strong_long_pe",
            "strong_short_pe",
            "short_covering_calls",
            "short_covering_puts",
            "counts",
            "actionable",
            "atm_band",
            "median_call_volume",
            "median_put_volume",
        )
    }

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
        buildup=buildup_summary,
        walls=walls,
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
        "walls": walls,
        "buildup": buildup_summary,
        "quant": quant,
    }
