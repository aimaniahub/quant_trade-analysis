"""
Option Flow Radar – Signal Engine v3
====================================
Pure scoring / classification / grading (Option_Flow_Radar_Complete_Specification_v3).

No I/O. Used by option_flow_radar.OptionFlowRadarService.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import math
import statistics

# ── Hard filters (spec §5) ──────────────────────────────────────
MAX_ATM_DISTANCE_PCT = 7.0
MIN_VOL_SPIKE = 1.5
MIN_OI_CHANGE_PCT = 8.0
MIN_OPTION_VOLUME = 150
MIN_PREMIUM_CHG_PCT = 1.5
MIN_GREEK_QUALITY = 8.0  # of 20 — below this hard-downgrades grade

# Alert Box thresholds (spec §8)
ALERT_OI_PCT = 25.0
ALERT_VOL_SPIKE = 3.0
ALERT_UNUSUAL_SCORE = 55.0
ALERT_ABS_OI_FLOOR = 50_000  # absolute OI contracts added (soft, scaled by price later)


# ─────────────────────────────────────────────────────────────────
# Classification (spec §3)
# ─────────────────────────────────────────────────────────────────

def classify_signal(
    oi_change_pct: float,
    option_price_change_pct: float,
    underlying_price_change_pct: float = 0.0,
    opt_type: str = "CE",
) -> Dict[str, str]:
    """Full CE/PE × OI × premium matrix with stock-side direction."""
    opt = (opt_type or "CE").upper()
    if opt not in ("CE", "PE"):
        opt = "CE"

    # Spec recommended thresholds: OI 8%, premium 1.5%
    oi_up = oi_change_pct >= MIN_OI_CHANGE_PCT
    oi_dn = oi_change_pct <= -MIN_OI_CHANGE_PCT
    pr_up = option_price_change_pct >= MIN_PREMIUM_CHG_PCT
    pr_dn = option_price_change_pct <= -MIN_PREMIUM_CHG_PCT

    if opt == "CE":
        if oi_up and pr_up:
            return _sig("STRONG_BULLISH", "Fresh Call Buying", "🟢", "emerald", "BULLISH")
        if oi_up and pr_dn:
            return _sig("BEARISH", "Call Writing", "🔴", "rose", "BEARISH")
        if oi_dn and pr_up:
            return _sig("EXHAUSTION", "Call Short Covering", "🟡", "amber", "BULLISH")
        if oi_dn and pr_dn:
            return _sig("EXHAUSTION", "Call Long Unwinding", "🔴", "rose", "BEARISH")

    if opt == "PE":
        if oi_up and pr_up:
            return _sig("STRONG_BEARISH", "Fresh Put Buying", "🔴", "rose", "BEARISH")
        if oi_up and pr_dn:
            return _sig("BULLISH", "Put Writing", "🟢", "emerald", "BULLISH")
        if oi_dn and pr_up:
            return _sig("EXHAUSTION", "Put Short Covering", "🟡", "amber", "BEARISH")
        if oi_dn and pr_dn:
            return _sig("EXHAUSTION", "Put Long Unwinding", "🟢", "emerald", "BULLISH")

    if oi_change_pct > 5:
        return _sig("ACCUMULATION", "Smart Money Accum.", "🔵", "blue", "NEUTRAL")

    return _sig("NEUTRAL", "Neutral/Inconclusive", "⚪", "zinc", "NEUTRAL")


def _sig(signal: str, label: str, icon: str, color: str, direction: str) -> Dict[str, str]:
    return {
        "signal": signal,
        "label": label,
        "icon": icon,
        "color": color,
        "direction": direction,
    }


# ─────────────────────────────────────────────────────────────────
# Momentum + LIS (spec §4)
# ─────────────────────────────────────────────────────────────────

def compute_momentum_score(
    option_price_change_pct: float,
    opt_type: str,
    direction: str = "NEUTRAL",
) -> float:
    opt = (opt_type or "").upper()
    d = (direction or "NEUTRAL").upper()
    chg = float(option_price_change_pct or 0.0)

    if d == "BULLISH":
        if opt == "CE" and chg > 0:
            return min(chg / 5.0, 1.0) * 15.0
        if opt == "PE" and chg < 0:
            return min(abs(chg) / 5.0, 1.0) * 12.0
    elif d == "BEARISH":
        if opt == "PE" and chg > 0:
            return min(chg / 5.0, 1.0) * 15.0
        if opt == "CE" and chg < 0:
            return min(abs(chg) / 5.0, 1.0) * 12.0
    return 0.0


def compute_lis_v2(
    oi_change_pct: float,
    vol_spike_ratio: float,
    option_price_change_pct: float,
    underlying_vwap_dev_pct: float,
    delivery_ratio: float,
    above_ema20: bool,
    opt_type: str = "CE",
    signal_direction: str = "NEUTRAL",
) -> float:
    oi_score = min(abs(oi_change_pct) / 20.0, 1.0) * 30.0
    vol_excess = max(vol_spike_ratio - 1.0, 0.0)
    vol_score = min(vol_excess / 4.0, 1.0) * 25.0
    momentum_score = compute_momentum_score(
        option_price_change_pct, opt_type, signal_direction
    )
    vwap_score = (1.0 - min(abs(underlying_vwap_dev_pct) / 2.0, 1.0)) * 15.0

    direction = (signal_direction or "NEUTRAL").upper()
    if direction == "BULLISH":
        trigger = 10.0 if above_ema20 else 0.0
    elif direction == "BEARISH":
        trigger = 10.0 if not above_ema20 else 0.0
    else:
        trigger = 5.0 if above_ema20 else 0.0

    delivery_score = min(max(delivery_ratio, 0.0) / 2.0, 1.0) * 5.0
    total = oi_score + vol_score + momentum_score + vwap_score + trigger + delivery_score
    return round(min(total, 100.0), 1)


# ─────────────────────────────────────────────────────────────────
# Greek Quality Score 0–20 (spec §6)
# ─────────────────────────────────────────────────────────────────

def compute_greek_quality_score(
    delta: Optional[float],
    gamma: Optional[float],
    theta: Optional[float],
    vega: Optional[float],
    iv: Optional[float],
    atm_dist_pct: float,
    opt_type: str = "CE",
) -> Dict[str, Any]:
    """
    Greeks filter quality of the selected strike — not primary signal.
    Returns score 0–20 + breakdown + reject flag for deep OTM delta.
    """
    abs_d = abs(float(delta or 0.0))
    g = abs(float(gamma or 0.0))
    th = abs(float(theta or 0.0))
    vg = abs(float(vega or 0.0))
    iv_f = float(iv or 0.0)
    score = 0.0
    notes: List[str] = []
    reject = False

    # Delta (0–8+2)
    if 0.30 <= abs_d <= 0.60:
        score += 8.0
        notes.append("delta sweet-spot")
    elif 0.20 <= abs_d < 0.30:
        score += 4.0
        notes.append("delta acceptable")
    elif abs_d > 0.70:
        score += 2.0
        notes.append("delta deep ITM / expensive")
    elif abs_d < 0.20:
        score += 0.0
        notes.append("delta too OTM")
        if abs_d < 0.12:
            reject = True
    else:
        # 0.60–0.70
        score += 5.0
        notes.append("delta near ITM")

    # Gamma healthy (0–4)
    if 0.001 <= g <= 0.05:
        score += 4.0
        notes.append("gamma healthy")
    elif g > 0.05:
        score += 1.0
        notes.append("gamma extreme / whipsaw")
    else:
        score += 2.0
        notes.append("gamma low")

    # Theta reasonable (0–3)
    if th <= 2.0:
        score += 3.0
        notes.append("theta low")
    elif th <= 8.0:
        score += 2.0
        notes.append("theta moderate")
    else:
        score += 0.0
        notes.append("theta high decay")

    # Vega / IV not hostile (0–3)
    if iv_f <= 0:
        score += 2.0
        notes.append("iv unknown")
    elif iv_f < 35:
        score += 3.0
        notes.append("iv calm")
    elif iv_f < 55:
        score += 2.0
        notes.append("iv elevated")
    else:
        score += 0.5
        notes.append("iv rich / hostile")

    # ATM + sweet delta bonus (0–2)
    if atm_dist_pct <= 3.0 and 0.30 <= abs_d <= 0.60:
        score += 2.0
        notes.append("atm+delta bonus")
    elif atm_dist_pct <= 5.0 and abs_d >= 0.25:
        score += 1.0

    score = round(min(20.0, max(0.0, score)), 1)
    return {
        "score": score,
        "max": 20.0,
        "reject_low_delta": reject,
        "abs_delta": round(abs_d, 4),
        "notes": notes,
    }


# ─────────────────────────────────────────────────────────────────
# Absolute OI added + chain-relative volume
# ─────────────────────────────────────────────────────────────────

def estimate_oi_added(oi: float, oi_change_pct: float, prev_oi: Optional[float] = None) -> float:
    if prev_oi is not None and prev_oi > 0:
        return float(prev_oi) * float(oi_change_pct) / 100.0
    oi = float(oi or 0)
    chg = float(oi_change_pct or 0)
    if oi <= 0 or chg <= -99.9:
        return 0.0
    # oi = prev * (1 + chg/100) → prev = oi / (1+chg/100)
    prev = oi / (1.0 + chg / 100.0)
    return oi - prev


def chain_relative_vol_spike(volume: float, peer_volumes: List[float]) -> float:
    """When 3-day history missing, use near-ATM peer median as baseline."""
    peers = [float(v) for v in peer_volumes if v and v > 0]
    if not peers:
        return 1.0
    if len(peers) >= 3:
        base = statistics.median(peers)
    else:
        base = sum(peers) / len(peers)
    if base <= 0:
        return 1.0
    return float(volume) / base


# ─────────────────────────────────────────────────────────────────
# Unusual Score 0–100 (spec §8)
# ─────────────────────────────────────────────────────────────────

def compute_unusual_score(
    oi_change_pct: float,
    vol_spike_ratio: float,
    oi_added: float,
    option_price_change_pct: float,
    iv: Optional[float],
    atm_dist_pct: float,
    cluster_hits: int = 0,
) -> Dict[str, Any]:
    score = 0.0
    reasons: List[str] = []

    # OI %
    oi_abs = abs(oi_change_pct)
    if oi_abs >= 40:
        score += 30.0
        reasons.append(f"OI {oi_change_pct:+.0f}% extreme")
    elif oi_abs >= ALERT_OI_PCT:
        score += 22.0
        reasons.append(f"OI {oi_change_pct:+.0f}% large")
    elif oi_abs >= 15:
        score += 12.0
    else:
        score += min(oi_abs / 15.0, 1.0) * 8.0

    # Volume multiple
    if vol_spike_ratio >= 5:
        score += 28.0
        reasons.append(f"Vol {vol_spike_ratio:.1f}× extreme")
    elif vol_spike_ratio >= ALERT_VOL_SPIKE:
        score += 22.0
        reasons.append(f"Vol {vol_spike_ratio:.1f}× spike")
    elif vol_spike_ratio >= 2.0:
        score += 12.0
    else:
        score += min(max(vol_spike_ratio - 1.0, 0) / 2.0, 1.0) * 8.0

    # Absolute OI size
    if abs(oi_added) >= 200_000:
        score += 20.0
        reasons.append(f"OI add {oi_added:,.0f} huge")
    elif abs(oi_added) >= ALERT_ABS_OI_FLOOR:
        score += 14.0
        reasons.append(f"OI add {oi_added:,.0f}")
    elif abs(oi_added) >= 15_000:
        score += 8.0
    else:
        score += min(abs(oi_added) / ALERT_ABS_OI_FLOOR, 1.0) * 6.0

    # Premium + IV expansion
    if abs(option_price_change_pct) >= 8 and (iv or 0) >= 30:
        score += 10.0
        reasons.append("premium+IV expansion")
    elif abs(option_price_change_pct) >= 5:
        score += 5.0

    # Slightly OTM abnormal size
    if 2.0 <= atm_dist_pct <= 6.0 and abs(oi_added) >= 30_000 and vol_spike_ratio >= 2.0:
        score += 8.0
        reasons.append("OTM size anomaly")

    # Cluster coordinated
    if cluster_hits >= 3:
        score += 12.0
        reasons.append(f"cluster {cluster_hits} strikes")
    elif cluster_hits >= 2:
        score += 6.0
        reasons.append("paired strike flow")

    score = round(min(100.0, score), 1)
    is_alert = (
        score >= ALERT_UNUSUAL_SCORE
        or (oi_abs >= ALERT_OI_PCT and vol_spike_ratio >= ALERT_VOL_SPIKE)
        or abs(oi_added) >= 150_000 and vol_spike_ratio >= 2.5
    )
    return {
        "score": score,
        "is_alert_box": is_alert,
        "reasons": reasons,
    }


# ─────────────────────────────────────────────────────────────────
# Multi-layer confirmation + grade (spec §7, §9)
# ─────────────────────────────────────────────────────────────────

def evaluate_layers(
    *,
    signal: Dict[str, str],
    vol_spike_ratio: float,
    atm_dist_pct: float,
    greek_quality: Dict[str, Any],
    direction: str,
    above_ema20: bool,
    spot_change_pct: float,
    vwap_dev_pct: float,
    unusual: Dict[str, Any],
    lis: float,
) -> Dict[str, Any]:
    """
    Layers 1–6. Actionable only when required layers pass.
    """
    sig_type = (signal.get("signal") or "NEUTRAL").upper()
    direction = (direction or signal.get("direction") or "NEUTRAL").upper()
    gq = float(greek_quality.get("score") or 0)
    abs_delta = float(greek_quality.get("abs_delta") or 0)

    layer1_flow = sig_type not in ("NEUTRAL",) and bool(signal.get("label"))
    layer2_volume = vol_spike_ratio >= MIN_VOL_SPIKE or vol_spike_ratio >= 1.2  # 1.2 if no hist baseline
    # Prefer true 1.5; allow pass mark if spike unknown (ratio==1.0) only for ACCUM with high OI via LIS path — strict:
    layer2_strict = vol_spike_ratio >= MIN_VOL_SPIKE
    layer3_strike = (
        atm_dist_pct <= MAX_ATM_DISTANCE_PCT
        and abs_delta >= 0.18
        and not greek_quality.get("reject_low_delta")
    )
    layer4_greeks = gq >= MIN_GREEK_QUALITY

    # Layer 5: underlying should not strongly oppose
    oppose = False
    if direction == "BULLISH":
        # Strong opposition: deep below VWAP + negative day + below EMA
        if spot_change_pct < -1.5 and vwap_dev_pct < -1.0 and not above_ema20:
            oppose = True
        aligned = above_ema20 or spot_change_pct >= 0 or vwap_dev_pct >= -0.5
    elif direction == "BEARISH":
        if spot_change_pct > 1.5 and vwap_dev_pct > 1.0 and above_ema20:
            oppose = True
        aligned = (not above_ema20) or spot_change_pct <= 0 or vwap_dev_pct <= 0.5
    else:
        aligned = True
    layer5_context = aligned and not oppose

    layer6_unusual = bool(unusual.get("is_alert_box"))

    layers = {
        "flow": layer1_flow,
        "volume": layer2_strict or (layer2_volume and lis >= 55),
        "strike": layer3_strike,
        "greeks": layer4_greeks,
        "underlying": layer5_context,
        "unusual": layer6_unusual,
    }
    passed = sum(1 for v in layers.values() if v)
    # Required for A: flow + volume + strike
    required_ok = layers["flow"] and layers["volume"] and layers["strike"]

    # Grade
    strong_flow = sig_type in ("STRONG_BULLISH", "STRONG_BEARISH", "BULLISH", "BEARISH")
    if (
        required_ok
        and layers["greeks"]
        and layers["underlying"]
        and layers["unusual"]
        and lis >= 60
        and strong_flow
    ):
        grade = "A+"
    elif required_ok and layers["greeks"] and layers["underlying"] and lis >= 50 and strong_flow:
        grade = "A"
    elif required_ok and strong_flow and lis >= 40:
        grade = "B"
    elif layers["flow"] and (layers["volume"] or layers["strike"]) and lis >= 35:
        grade = "B"
    else:
        grade = "C"

    # Soft downgrade: high LIS alone cannot stay A without greeks
    if grade in ("A", "A+") and not layers["greeks"]:
        grade = "B"
    if grade == "A+" and oppose:
        grade = "B"
    if greek_quality.get("reject_low_delta"):
        grade = "C"

    actionable = grade in ("A", "A+")
    watch_only = grade == "B"

    conviction = _conviction_from_grade(grade, lis, layers, sig_type)

    return {
        "layers": layers,
        "layers_passed": passed,
        "layers_total": 6,
        "required_ok": required_ok,
        "grade": grade,
        "actionable": actionable,
        "watch_only": watch_only,
        "conviction": conviction,
        "composite_score": round(
            lis * 0.55
            + gq * 2.0  # scale 20 → 40 max, *2 = 40
            + float(unusual.get("score") or 0) * 0.25
            + (10 if layers["underlying"] else 0),
            1,
        ),
    }


def _conviction_from_grade(
    grade: str, lis: float, layers: Dict[str, bool], signal_type: str
) -> Dict[str, str]:
    if grade == "A+":
        return {"level": "HIGH", "icon": "🔴", "label": "High Conviction"}
    if grade == "A":
        return {"level": "HIGH", "icon": "🔴", "label": "High Conviction"} if lis >= 65 else {
            "level": "MEDIUM",
            "icon": "🟡",
            "label": "Medium",
        }
    if grade == "B":
        return {"level": "MEDIUM", "icon": "🟡", "label": "Medium"} if lis >= 45 else {
            "level": "LOW",
            "icon": "⚪",
            "label": "Low",
        }
    return {"level": "LOW", "icon": "⚪", "label": "Low"}


def count_cluster_hits(
    candidates: List[Dict[str, Any]],
    strike: float,
    opt_type: str,
    direction: str,
    max_strike_steps: int = 2,
    step_guess: float = 0.0,
) -> int:
    """
    Count nearby strikes (same side + same direction) with valid flow.
    step_guess: approximate strike spacing; if 0, use min positive gap.
    """
    same = [
        c
        for c in candidates
        if c.get("opt_type") == opt_type
        and (c.get("prelim_signal") or {}).get("direction") == direction
    ]
    if len(same) < 2:
        return 1 if same else 0

    strikes = sorted({float(c["strike"]) for c in same})
    if not step_guess:
        gaps = [strikes[i + 1] - strikes[i] for i in range(len(strikes) - 1) if strikes[i + 1] > strikes[i]]
        step_guess = min(gaps) if gaps else 5.0
    window = step_guess * max_strike_steps + 0.01
    hits = sum(1 for c in same if abs(float(c["strike"]) - float(strike)) <= window)
    return hits


def interpret_greeks(
    delta: Optional[float],
    gamma: Optional[float],
    theta: Optional[float],
    vega: Optional[float],
    opt_type: str,
) -> Dict[str, Any]:
    d = delta or 0.0
    g = gamma or 0.0
    t = theta or 0.0
    v = vega or 0.0
    abs_d = abs(d)
    if abs_d >= 0.6:
        delta_bias, delta_label = "DEEP_ITM", "Deep ITM"
    elif abs_d >= 0.4:
        delta_bias, delta_label = "ATM", "Near ATM"
    elif abs_d >= 0.2:
        delta_bias, delta_label = "OTM", "OTM"
    else:
        delta_bias, delta_label = "DEEP_OTM", "Deep OTM"

    if g >= 0.01:
        gamma_risk = "HIGH"
    elif g >= 0.003:
        gamma_risk = "MEDIUM"
    else:
        gamma_risk = "LOW"

    theta_daily = abs(t)
    if theta_daily >= 5:
        theta_label, theta_risk = f"-₹{theta_daily:.1f}/day", "HIGH"
    elif theta_daily >= 1:
        theta_label, theta_risk = f"-₹{theta_daily:.1f}/day", "MEDIUM"
    else:
        theta_label, theta_risk = f"-₹{theta_daily:.2f}/day", "LOW"

    if v >= 10:
        vega_sens = "HIGH"
    elif v >= 3:
        vega_sens = "MEDIUM"
    else:
        vega_sens = "LOW"

    return {
        "delta_bias": delta_bias,
        "delta_label": delta_label,
        "delta_value": round(d, 4),
        "gamma_risk": gamma_risk,
        "gamma_value": round(g, 6),
        "theta_risk": theta_risk,
        "theta_label": theta_label,
        "theta_value": round(t, 2),
        "vega_sensitivity": vega_sens,
        "vega_value": round(v, 2),
    }


def build_scored_contract(
    *,
    symbol: str,
    name: str,
    nearest_expiry: str,
    cand: Dict[str, Any],
    signal: Dict[str, str],
    vol_3day_avg: float,
    vol_spike_ratio: float,
    vol_spike_source: str,
    spot: float,
    ul_chg_pct: float,
    vwap_dev: float,
    above_ema: bool,
    cluster_hits: int,
) -> Optional[Dict[str, Any]]:
    """
    Full v3 score path for one candidate. Returns None if hard-rejected (grade C with no alert).
    """
    opt = cand["opt"]
    direction = signal.get("direction") or "NEUTRAL"
    oi_added = estimate_oi_added(
        cand["oi"], cand["oi_change_pct"], opt.get("prev_oi")
    )

    greek_q = compute_greek_quality_score(
        delta=opt.get("delta"),
        gamma=opt.get("gamma"),
        theta=opt.get("theta"),
        vega=opt.get("vega"),
        iv=cand.get("iv"),
        atm_dist_pct=cand["atm_dist_pct"],
        opt_type=cand["opt_type"],
    )
    if greek_q.get("reject_low_delta") and cand["atm_dist_pct"] > 4.0:
        return None

    lis = compute_lis_v2(
        oi_change_pct=cand["oi_change_pct"],
        vol_spike_ratio=vol_spike_ratio,
        option_price_change_pct=cand["ltp_chg_pct"],
        underlying_vwap_dev_pct=vwap_dev,
        delivery_ratio=1.0,
        above_ema20=above_ema,
        opt_type=cand["opt_type"],
        signal_direction=direction,
    )

    unusual = compute_unusual_score(
        oi_change_pct=cand["oi_change_pct"],
        vol_spike_ratio=vol_spike_ratio,
        oi_added=oi_added,
        option_price_change_pct=cand["ltp_chg_pct"],
        iv=cand.get("iv"),
        atm_dist_pct=cand["atm_dist_pct"],
        cluster_hits=cluster_hits,
    )

    evald = evaluate_layers(
        signal=signal,
        vol_spike_ratio=vol_spike_ratio,
        atm_dist_pct=cand["atm_dist_pct"],
        greek_quality=greek_q,
        direction=direction,
        above_ema20=above_ema,
        spot_change_pct=ul_chg_pct,
        vwap_dev_pct=vwap_dev,
        unusual=unusual,
        lis=lis,
    )

    # Drop pure junk (C and not unusual)
    if evald["grade"] == "C" and not unusual["is_alert_box"]:
        return None

    greek_interp = interpret_greeks(
        opt.get("delta"), opt.get("gamma"), opt.get("theta"), opt.get("vega"), cand["opt_type"]
    )

    unusual_flags: List[str] = list(unusual.get("reasons") or [])
    if abs(cand["oi_change_pct"]) > 20:
        unusual_flags.append(f"OI spike {cand['oi_change_pct']:+.1f}%")
    if vol_spike_ratio >= 2:
        unusual_flags.append(f"Vol {vol_spike_ratio:.1f}×")
    if cand.get("iv") and cand["iv"] > 40:
        unusual_flags.append(f"High IV {cand['iv']:.0f}%")
    if cand["atm_dist_pct"] < 1:
        unusual_flags.append("ATM")
    if direction in ("BULLISH", "BEARISH"):
        unusual_flags.append(f"Dir {direction}")
    unusual_flags.append(f"Grade {evald['grade']}")

    from datetime import datetime

    return {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "name": name,
        "expiry": nearest_expiry,
        "strike": cand["strike"],
        "type": cand["opt_type"],
        "ltp": round(cand["ltp"], 2),
        "ltp_change_pct": round(cand["ltp_chg_pct"], 2),
        "oi": cand["oi"],
        "oi_change_pct": round(cand["oi_change_pct"], 2),
        "oi_added": round(oi_added, 0),
        "volume": cand["volume"],
        "vol_3day_avg": round(vol_3day_avg, 0),
        "vol_spike_ratio": round(vol_spike_ratio, 2),
        "vol_spike_source": vol_spike_source,
        "iv": round(cand["iv"], 2) if cand.get("iv") else None,
        "delta": opt.get("delta"),
        "gamma": opt.get("gamma"),
        "theta": opt.get("theta"),
        "vega": opt.get("vega"),
        "greek_interpretation": greek_interp,
        "greek_quality": greek_q,
        "spot": round(spot, 2),
        "spot_change_pct": round(ul_chg_pct, 2),
        "vwap_dev_pct": round(vwap_dev, 2),
        "above_ema20": above_ema,
        "atm_dist_pct": round(cand["atm_dist_pct"], 2),
        "lis": lis,
        "signal": signal,
        "direction": direction,
        "conviction": evald["conviction"],
        "grade": evald["grade"],
        "actionable": evald["actionable"],
        "watch_only": evald["watch_only"],
        "layers": evald["layers"],
        "layers_passed": evald["layers_passed"],
        "composite_score": evald["composite_score"],
        "unusual_score": unusual["score"],
        "alert_box": unusual["is_alert_box"],
        "cluster_hits": cluster_hits,
        "unusual_flags": unusual_flags[:12],
        "engine": "v3",
    }
