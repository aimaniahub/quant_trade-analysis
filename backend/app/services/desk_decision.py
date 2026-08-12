"""
Option Chain Analyzer – hardened decision engine.

Priority order (NON-NEGOTIABLE — see Option_Chain_Analyzer_Fix_Report.md):

  1. HTF Gate (Daily / 4H)     — hard max_score + side_preference
  2. OI PCR + Volume PCR       — structural ceiling / floor penalties
  3. Buildup + Strength        — flow quality (confirmed by structure)
  4. Gamma Wall + Max Pain     — mechanical pressure
  5. IV Skew + Premium         — flat skew = zero edge
  6. 15-min Technical Stack    — timing only
  7. Final score + action      — default WAIT on conflict

Buildup alone must NEVER override HTF + PCR opposition into aggressive BUY.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return float(default)
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _s(v: Any, default: str = "") -> str:
    if v is None:
        return default
    return str(v).strip()


def extract_atm_leg_states(buildup: Optional[Dict]) -> Dict[str, str]:
    """Best-effort ATM call/put buildup states from buildup summary."""
    buildup = buildup or {}
    call_bu = "Churn / Neutral"
    put_bu = "Churn / Neutral"

    band = buildup.get("atm_band") or []
    if band:
        mid = band[len(band) // 2]
        for row in band:
            if row.get("is_atm"):
                mid = row
                break
        call_bu = (mid.get("call") or {}).get("state") or call_bu
        put_bu = (mid.get("put") or {}).get("state") or put_bu
    else:
        primary = buildup.get("primary_state") or ""
        if primary == "Long Buildup" or (
            "Long Buildup" in primary and buildup.get("bias") == "BULLISH"
        ):
            call_bu = "Long Buildup"
        elif "Short Buildup" in primary:
            call_bu = "Short Buildup"
        if int(buildup.get("short_covering_puts") or 0) > 0 or "Short Covering" in primary:
            put_bu = "Short Covering"

    # Prefer strong actionable CE/PE near ATM when present
    for a in buildup.get("actionable") or []:
        side = (a.get("side") or "").upper()
        st = a.get("state") or ""
        if not st:
            continue
        if side == "CE" and (a.get("strength") == "Strong" or call_bu == "Churn / Neutral"):
            call_bu = st
        if side == "PE" and (a.get("strength") == "Strong" or put_bu == "Churn / Neutral"):
            put_bu = st

    return {"atm_call_buildup": call_bu, "atm_put_buildup": put_bu}


def build_decision_input(
    *,
    spot: float,
    pcr: Optional[Dict] = None,
    buildup: Optional[Dict] = None,
    greeks: Optional[Dict] = None,
    max_pain_pack: Optional[Dict] = None,
    iv: Optional[Dict] = None,
    tech: Optional[Dict] = None,
    premium: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Map our analytics packs into the flat decision dict."""
    pcr = pcr or {}
    buildup = buildup or {}
    greeks = greeks or {}
    max_pain_pack = max_pain_pack or {}
    iv = iv or {}
    tech = tech or {}
    premium = premium or {}
    legs = extract_atm_leg_states(buildup)

    # HTF: prefer nested htf.bias
    htf_daily = (
        (tech.get("htf") or {}).get("bias")
        or tech.get("htf_bias")
        or "NEUTRAL"
    )
    if htf_daily not in ("BULLISH", "BEARISH", "NEUTRAL"):
        htf_daily = "NEUTRAL"

    # 15m: map ema_stack / bias → BULLISH | MIXED | BEARISH
    intra = tech.get("intraday") or {}
    stack = (intra.get("ema_stack") or "").upper()
    id_bias = (intra.get("bias") or tech.get("bias") or "NEUTRAL").upper()
    if stack == "BULL" or id_bias == "BULLISH":
        tech_15m = "BULLISH"
    elif stack == "BEAR" or id_bias == "BEARISH":
        tech_15m = "BEARISH"
    else:
        tech_15m = "MIXED"

    strength = buildup.get("conviction") or "MEDIUM"
    # Normalize strength labels used in report
    if strength in ("HIGH", "Strong"):
        strength = "HIGH"
    elif strength in ("MEDIUM", "Moderate", "Weak"):
        strength = "MEDIUM" if strength != "Weak" else "WEAK"
    else:
        strength = "MEDIUM"

    gamma_bias = greeks.get("delta_bias") or "NEUTRAL"
    # Prefer explicit gamma bias if present
    if greeks.get("gamma_bias"):
        gamma_bias = greeks["gamma_bias"]

    return {
        "htf_daily": htf_daily,
        "oi_pcr": _f(pcr.get("oi_pcr"), 1.0),
        "vol_pcr": _f(pcr.get("volume_pcr"), 1.0),
        "atm_pcr": _f(pcr.get("atm_oi_pcr"), 1.0),
        "atm_call_buildup": legs["atm_call_buildup"],
        "atm_put_buildup": legs["atm_put_buildup"],
        "buildup_strength": strength,
        "buildup_primary": buildup.get("primary_state"),
        "gamma_wall": greeks.get("gamma_wall_strike"),
        "gamma_bias": gamma_bias,
        "max_pain": max_pain_pack.get("max_pain"),
        "spot": _f(spot),
        "iv_skew": _f(iv.get("skew"), 0.0),
        "straddle_change_pct": _f(premium.get("straddle_chg_pct"), 0.0),
        "tech_15m": tech_15m,
        "volume_vs_avg": _f(intra.get("volume_ratio"), 1.0),
        # Option-strike volume features (from PCR pack / chain)
        "atm_call_volume": _f(pcr.get("atm_call_volume")),
        "atm_put_volume": _f(pcr.get("atm_put_volume")),
        "ce_vol_share": _f(pcr.get("ce_vol_share"), 0.5),
        "pe_vol_share": _f(pcr.get("pe_vol_share"), 0.5),
        "atm_ce_vol_share": _f(pcr.get("atm_ce_vol_share"), 0.5),
        "band_ce_vol_share": _f(pcr.get("band_ce_vol_share"), 0.5),
        "atm_ce_rel_vol": _f(pcr.get("atm_ce_rel_vol"), 1.0),
        "atm_pe_rel_vol": _f(pcr.get("atm_pe_rel_vol"), 1.0),
        "premium_flags": list(premium.get("flags") or []),
        "squeeze_risk": bool(premium.get("squeeze_risk")),
        "vol_expand_risk": bool(premium.get("vol_expand_risk")),
    }


def get_final_bias_and_score(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Corrected scoring from Option_Chain_Analyzer_Fix_Report.md §5.
    """
    factors: List[str] = []

    # ----- 1. HTF GATE (Hard Filter) -----
    htf = _s(data.get("htf_daily"), "NEUTRAL").upper() or "NEUTRAL"
    oi_pcr = _f(data.get("oi_pcr"), 1.0)
    vol_pcr = _f(data.get("vol_pcr"), 1.0)

    if htf == "BEARISH":
        max_score = 58.0
        side_pref = "SHORT_PREFERRED" if oi_pcr < 0.75 else "NEUTRAL"
        factors.append(f"HTF BEARISH → max score capped at {max_score:.0f}")
    elif htf == "BULLISH":
        max_score = 92.0
        side_pref = "LONG_PREFERRED"
        factors.append("HTF BULLISH → long preferred (cap 92)")
    else:
        max_score = 75.0
        side_pref = "NEUTRAL"
        factors.append("HTF NEUTRAL → cap 75")

    # ----- 2. PCR REGIME -----
    pcr_penalty = 0.0
    if oi_pcr < 0.70:
        pcr_regime = "CALL_WRITING_CEILING"
        pcr_penalty = 12.0
        factors.append(f"OI PCR {oi_pcr:.2f} → CALL_WRITING_CEILING (−12)")
    elif oi_pcr > 1.25:
        pcr_regime = "PUT_WRITING_FLOOR"
        pcr_penalty = -8.0  # bonus
        factors.append(f"OI PCR {oi_pcr:.2f} → PUT_WRITING_FLOOR (+8)")
    else:
        pcr_regime = "BALANCED"
        pcr_penalty = 0.0

    if vol_pcr < 0.45:
        pcr_penalty += 6.0
        factors.append(f"Vol PCR {vol_pcr:.2f} aggressive call activity (−6)")

    # ----- 3. BUILDUP QUALITY -----
    call_bu = _s(data.get("atm_call_buildup"), "Churn / Neutral")
    put_bu = _s(data.get("atm_put_buildup"), "Churn / Neutral")
    strength = _s(data.get("buildup_strength"), "MEDIUM").upper()
    if strength in ("STRONG",):
        strength = "HIGH"

    if call_bu == "Long Buildup" and strength == "HIGH":
        flow_score = 28.0
        narrative = "Call Long Buildup (HIGH)"
    elif call_bu == "Long Buildup":
        flow_score = 18.0
        narrative = "Call Long Buildup (Moderate)"
    elif put_bu == "Short Covering" or call_bu == "Short Covering":
        flow_score = 14.0
        narrative = "Put Short Covering only" if put_bu == "Short Covering" else "Short Covering"
    elif call_bu == "Short Buildup" and strength == "HIGH":
        flow_score = 26.0
        narrative = "Call Short Buildup (HIGH) — bearish flow"
    elif put_bu == "Long Buildup" and strength in ("HIGH", "MEDIUM"):
        flow_score = 22.0
        narrative = "Put Long Buildup — fresh bearish money"
    else:
        flow_score = 8.0
        narrative = "No clear directional flow"

    # Dual-side confirmation bonus (long only when structure can support)
    dual_confirm = False
    if call_bu == "Long Buildup" and put_bu in ("Short Covering", "Long Unwinding"):
        flow_score += 6.0
        dual_confirm = True
        narrative += " + Put support"
        factors.append("Dual-side confirm: CE Long Buildup + Put support (+6)")

    # ----- 3b. OPTION + UNDERLYING VOLUME WEIGHTING -----
    # Uses strike volumes (ATM/band CE/PE) + underlying relative volume
    atm_ce_rel = _f(data.get("atm_ce_rel_vol"), 1.0)
    atm_pe_rel = _f(data.get("atm_pe_rel_vol"), 1.0)
    atm_ce_share = _f(data.get("atm_ce_vol_share"), 0.5)
    band_ce_share = _f(data.get("band_ce_vol_share"), 0.5)
    ce_share = _f(data.get("ce_vol_share"), 0.5)
    und_vol = _f(data.get("volume_vs_avg"), 1.0)

    vol_confirm_long = False
    vol_confirm_short = False
    vol_boost = 0.0

    # High ATM CE volume vs median + CE share → confirms bullish option participation
    if call_bu == "Long Buildup":
        if atm_ce_rel >= 1.5 and atm_ce_share >= 0.55:
            vol_boost += 5.0
            vol_confirm_long = True
            factors.append(
                f"ATM CE vol strong ({atm_ce_rel:.1f}× median, share {atm_ce_share:.0%}) (+5)"
            )
        elif atm_ce_rel >= 1.2 or band_ce_share >= 0.58:
            vol_boost += 3.0
            vol_confirm_long = True
            factors.append(f"ATM/band CE volume elevated (+3)")
        if und_vol >= 1.2:
            vol_boost += 3.0
            vol_confirm_long = True
            factors.append(f"Underlying vol {und_vol:.2f}× avg (+3)")
        elif und_vol < 0.7:
            vol_boost -= 2.0
            factors.append(f"Underlying vol weak {und_vol:.2f}× (−2)")

    # High ATM PE volume confirms bearish option demand
    if put_bu == "Long Buildup" or call_bu == "Short Buildup":
        if atm_pe_rel >= 1.5 and atm_ce_share <= 0.45:
            vol_boost += 5.0
            vol_confirm_short = True
            factors.append(f"ATM PE vol strong ({atm_pe_rel:.1f}×) (+5 bearish flow)")
        if und_vol >= 1.2:
            vol_boost += 2.0
            vol_confirm_short = True

    # Low option volume degrades pure OI-based buildup (churn risk)
    if call_bu == "Long Buildup" and atm_ce_rel < 0.6 and und_vol < 0.85:
        vol_boost -= 4.0
        factors.append("Thin ATM CE + stock volume — buildup less reliable (−4)")

    flow_score = max(4.0, flow_score + vol_boost)
    factors.append(f"Flow: {narrative} (flow_score={flow_score:.0f})")

    # ----- 4. GAMMA + MAX PAIN -----
    gamma_penalty = 0.0
    spot = _f(data.get("spot"))
    gamma_wall = data.get("gamma_wall")
    gamma_bias = _s(data.get("gamma_bias"), "NEUTRAL").upper()
    if gamma_wall is not None and spot > 0:
        try:
            gw = float(gamma_wall)
            if abs(gw - spot) < (spot * 0.008):
                if gamma_bias == "BEARISH":
                    gamma_penalty = 7.0
                    factors.append(f"Gamma wall BEARISH near spot ({gw}) (−7)")
                elif gamma_bias == "BULLISH":
                    gamma_penalty = -5.0
                    factors.append(f"Gamma wall BULLISH near spot ({gw}) (+5)")
        except (TypeError, ValueError):
            pass

    max_pain = data.get("max_pain")
    max_pain_bonus = 0.0
    if max_pain is not None and spot > 0:
        try:
            mp = float(max_pain)
            # Report: spot < max_pain → +4 else −3
            if spot < mp:
                max_pain_bonus = 4.0
                factors.append(f"Spot below max pain {mp} (+4)")
            else:
                max_pain_bonus = -3.0
                factors.append(f"Spot at/above max pain {mp} (−3)")
        except (TypeError, ValueError):
            pass

    # ----- 5. IV SKEW + PREMIUM -----
    iv_skew = _f(data.get("iv_skew"), 0.0)
    if iv_skew > 3.5:
        skew_score = 6.0
        factors.append(f"IV skew +{iv_skew:.1f} put-rich edge (+6)")
        skew_label = "PUT_RICH"
    elif iv_skew < -2.0:
        skew_score = -5.0
        factors.append(f"IV skew {iv_skew:.1f} call-rich (−5)")
        skew_label = "CALL_RICH"
    else:
        skew_score = 0.0
        factors.append("IV Skew FLAT → No Volatility Edge (0)")
        skew_label = "FLAT"

    straddle_chg = _f(data.get("straddle_change_pct"), 0.0)
    if straddle_chg > 4:
        premium_score = 14.0
        factors.append(f"Straddle +{straddle_chg:.1f}% expansion (+14)")
    elif straddle_chg > 0:
        premium_score = 9.0
    else:
        premium_score = 5.0
        if abs(straddle_chg) < 1e-9:
            factors.append("Premium stable (no expansion)")

    # ----- 6. 15-min TECHNICAL -----
    tech = _s(data.get("tech_15m"), "MIXED").upper() or "MIXED"
    vol_ratio = _f(data.get("volume_vs_avg"), 1.0)
    if tech == "BULLISH" and vol_ratio > 1.1:
        tech_score = 28.0
        factors.append(f"15m BULLISH + vol {vol_ratio:.2f}× (+28)")
    elif tech == "BULLISH":
        tech_score = 20.0
        factors.append("15m BULLISH (+20)")
    elif tech == "MIXED":
        tech_score = 12.0
        factors.append("15m MIXED — reduced tech score (+12)")
    else:
        tech_score = 6.0
        factors.append("15m BEARISH / opposing (+6)")

    # ----- FINAL SCORE -----
    raw = (
        flow_score
        + tech_score
        + premium_score
        + skew_score
        + max_pain_bonus
        - pcr_penalty
        - gamma_penalty
    )
    final = max(min(raw, max_score), 15.0)

    # Flow vs structure:
    # hard = Long Buildup vs BOTH HTF bear + call-writing ceiling (LICHSGFIN)
    # soft = only one structural opponent — lean stays bullish, action usually WAIT
    hard_conflict = bool(
        call_bu == "Long Buildup"
        and htf == "BEARISH"
        and pcr_regime == "CALL_WRITING_CEILING"
    )
    soft_conflict = bool(
        call_bu == "Long Buildup"
        and (htf == "BEARISH" or pcr_regime == "CALL_WRITING_CEILING")
        and not hard_conflict
    )
    conflicted = hard_conflict or soft_conflict
    bearish_flow = call_bu == "Short Buildup" or put_bu == "Long Buildup"
    bullish_flow = call_bu == "Long Buildup" and not bearish_flow

    # Directional LEAN for UI columns (independent of WAIT action)
    if bullish_flow:
        lean_bias = "BULLISH"
    elif bearish_flow:
        lean_bias = "BEARISH"
    elif side_pref == "LONG_PREFERRED":
        lean_bias = "BULLISH"
    elif side_pref == "SHORT_PREFERRED":
        lean_bias = "BEARISH"
    else:
        lean_bias = "NEUTRAL"

    # ----- ACTION RULES (strict) -----
    # Volume-rescued cautious long: soft conflict only + strong option/stock volume
    volume_rescued = bool(
        soft_conflict
        and vol_confirm_long
        and dual_confirm
        and und_vol >= 1.0
        and final >= 48
    )

    if hard_conflict:
        action, conviction = "WAIT", "LOW / CONFLICTED"
        factors.append("Hard conflict (HTF bear + call ceiling) → WAIT; lean still shown")
    elif volume_rescued:
        action, conviction = "BUY_CAUTIOUS", "MEDIUM"
        factors.append(
            "Soft conflict but CE+stock volume confirms → BUY_CAUTIOUS (defined-risk)"
        )
    elif soft_conflict and not volume_rescued:
        action, conviction = "WAIT", "LOW / CONFLICTED"
        factors.append("Soft conflict → WAIT (watchlist lean bullish if flow says so)")
    elif final >= 72 and side_pref == "LONG_PREFERRED":
        action, conviction = "BUY", "HIGH"
    elif final >= 58 and side_pref == "LONG_PREFERRED" and vol_confirm_long:
        action, conviction = "BUY_CAUTIOUS", "MEDIUM"
        factors.append("HTF long + volume-confirmed flow → BUY_CAUTIOUS")
    elif final >= 62 and side_pref != "SHORT_PREFERRED" and bullish_flow:
        action, conviction = "BUY_CAUTIOUS", "MEDIUM"
    elif final >= 55 and bullish_flow and vol_confirm_long and htf != "BEARISH":
        # Allow cautious long when flow+volume strong even if HTF neutral
        action, conviction = "BUY_CAUTIOUS", "MEDIUM"
        factors.append("Volume-confirmed Long Buildup + non-bear HTF → BUY_CAUTIOUS")
    elif final <= 42 and side_pref == "SHORT_PREFERRED" and bearish_flow:
        action, conviction = "SELL", "MEDIUM-HIGH"
    elif final <= 48 and bearish_flow and vol_confirm_short and htf != "BULLISH":
        action, conviction = "SELL", "MEDIUM"
        factors.append("Volume-confirmed bearish flow → SELL")
    else:
        action, conviction = "WAIT", "LOW / WATCH"
        if bullish_flow:
            factors.append("Bullish lean — WAIT for better stack (still listed bullish)")
        elif bearish_flow:
            factors.append("Bearish lean — WAIT for better stack (still listed bearish)")

    # bias used for setup_side columns = lean (so bullish names still appear)
    bias = lean_bias

    # Entry flags for UI
    entry_long = action in ("BUY", "BUY_CAUTIOUS")
    entry_short = action == "SELL"
    watch_long = bool(bullish_flow and action == "WAIT")
    watch_short = bool(bearish_flow and action == "WAIT")

    # Defined-risk note when flat skew or conflicted
    structure_note = None
    if skew_label == "FLAT":
        structure_note = "No Volatility Edge — prefer defined-risk (spreads) over naked"
    if hard_conflict:
        structure_note = (
            "Fresh bullish flow fighting call-writing ceiling + HTF bearish. "
            "Listed as BULLISH watch — no entry until structure turns."
        )
    elif soft_conflict and action == "WAIT":
        structure_note = (
            "Bullish flow with one structural headwind"
            + (" (HTF bear)" if htf == "BEARISH" else "")
            + (" (call-writing ceiling)" if pcr_regime == "CALL_WRITING_CEILING" else "")
            + ". Watch / defined-risk only until confirmed."
        )
    elif volume_rescued:
        structure_note = (
            "Soft structural conflict but ATM CE + stock volume confirms — "
            "cautious defined-risk long only."
        )

    verdict = _build_verdict(
        final, action, conviction, narrative, pcr_regime, oi_pcr, htf, max_score,
        gamma_bias, gamma_wall, skew_label, tech, structure_note,
    )

    return {
        "score": round(final, 1),
        "raw_score": round(raw, 1),
        "action": action,
        "conviction": conviction,
        "bias": bias,
        "narrative": narrative,
        "pcr_regime": pcr_regime,
        "side_preference": side_pref,
        "max_score_cap": max_score,
        "flow_score": round(flow_score, 1),
        "tech_score": round(tech_score, 1),
        "premium_score": round(premium_score, 1),
        "skew_score": round(skew_score, 1),
        "skew_label": skew_label,
        "pcr_penalty": round(pcr_penalty, 1),
        "gamma_penalty": round(gamma_penalty, 1),
        "max_pain_bonus": round(max_pain_bonus, 1),
        "dual_confirm": dual_confirm,
        "conflicted": conflicted,
        "hard_conflict": hard_conflict,
        "soft_conflict": soft_conflict,
        "vol_confirm_long": vol_confirm_long,
        "vol_confirm_short": vol_confirm_short,
        "lean_bias": lean_bias,
        "entry_long": entry_long,
        "entry_short": entry_short,
        "watch_long": watch_long,
        "watch_short": watch_short,
        "allow_directional_buy": action in ("BUY", "BUY_CAUTIOUS"),
        "prefer_defined_risk": (
            skew_label == "FLAT"
            or conflicted
            or action == "BUY_CAUTIOUS"
            or watch_long
        ),
        "verdict": verdict,
        "structure_note": structure_note,
        "factors": factors[:14],
        "components": {
            "flow_score": round(flow_score, 1),
            "tech_score": round(tech_score, 1),
            "premium_score": round(premium_score, 1),
            "skew_score": round(skew_score, 1),
            "max_pain_bonus": round(max_pain_bonus, 1),
            "pcr_penalty": round(pcr_penalty, 1),
            "gamma_penalty": round(gamma_penalty, 1),
            "raw": round(raw, 1),
            "max_score_cap": max_score,
            "total": round(final, 1),
            # UI compatibility (old 40/40/20 buckets — approximate)
            "option_score": round(min(40.0, flow_score + max(0, -pcr_penalty) * 0.3), 1),
            "tech_score_ui": round(min(40.0, tech_score), 1),
            "premium_score_ui": round(min(20.0, premium_score), 1),
        },
    }


def _build_verdict(
    score: float,
    action: str,
    conviction: str,
    narrative: str,
    pcr_regime: str,
    oi_pcr: float,
    htf: str,
    max_score: float,
    gamma_bias: str,
    gamma_wall: Any,
    skew_label: str,
    tech_15m: str,
    structure_note: Optional[str],
) -> str:
    lines = [
        f"Score: {score:.1f} · Action: {action} · Conviction: {conviction}",
        f"Primary Flow: {narrative}",
        f"Structure: {pcr_regime} (OI PCR {oi_pcr:.2f})",
        f"HTF: {htf} → max score capped at {max_score:.0f}",
        f"Gamma: {gamma_bias}" + (f" wall at {gamma_wall}" if gamma_wall else ""),
        f"IV Skew: {skew_label}" + (" → No Volatility Edge" if skew_label == "FLAT" else ""),
        f"15m: {tech_15m}",
    ]
    if structure_note:
        lines.append(f"Verdict: {structure_note}")
    elif action == "WAIT":
        lines.append("Verdict: Stand aside — wait for structure/HTF alignment.")
    elif action == "BUY":
        lines.append("Verdict: Stack aligned — directional long allowed.")
    elif action == "BUY_CAUTIOUS":
        lines.append("Verdict: Cautious long only — prefer defined-risk.")
    elif action == "SELL":
        lines.append("Verdict: Bearish structure + HTF — short side preferred.")
    return "\n".join(lines)


def fuse_with_hardened_decision(
    quant: Optional[Dict],
    buildup: Optional[Dict],
    tech: Optional[Dict],
    premium: Optional[Dict],
    *,
    pcr: Optional[Dict] = None,
    greeks: Optional[Dict] = None,
    max_pain: Optional[Dict] = None,
    iv: Optional[Dict] = None,
    spot: float = 0.0,
) -> Dict[str, Any]:
    """
    Drop-in replacement path for fuse_desk_conviction.
    Produces quant_* compatible fields + report fields.
    """
    quant = dict(quant or {})
    decision_in = build_decision_input(
        spot=spot,
        pcr=pcr,
        buildup=buildup,
        greeks=greeks,
        max_pain_pack=max_pain,
        iv=iv,
        tech=tech,
        premium=premium,
    )
    decision = get_final_bias_and_score(decision_in)

    factors = list(decision.get("factors") or [])
    # Keep a few prior quant factors that aren't redundant
    for f in (quant.get("factors") or [])[:3]:
        if f not in factors:
            factors.append(f)

    return {
        **quant,
        "quant_score": decision["score"],
        "bias": decision["bias"],
        "conviction": decision["conviction"],
        "factors": factors[:14],
        "primary_buildup": quant.get("primary_buildup")
        or (buildup or {}).get("primary_state"),
        "buildup_note": decision.get("narrative")
        or quant.get("buildup_note")
        or (buildup or {}).get("note"),
        "entry_long": decision["entry_long"],
        "entry_short": decision["entry_short"],
        "watch_long": decision.get("watch_long"),
        "watch_short": decision.get("watch_short"),
        "lean_bias": decision.get("lean_bias") or decision["bias"],
        "vol_confirm_long": decision.get("vol_confirm_long"),
        "vol_confirm_short": decision.get("vol_confirm_short"),
        "squeeze_risk": bool((premium or {}).get("squeeze_risk")),
        "vol_expand_risk": bool((premium or {}).get("vol_expand_risk")),
        "tech_aligned": bool((tech or {}).get("aligned")),
        "action": decision["action"],
        "side_preference": decision["side_preference"],
        "max_score_cap": decision["max_score_cap"],
        "pcr_regime": decision["pcr_regime"],
        "verdict": decision["verdict"],
        "conflicted": decision["conflicted"],
        "prefer_defined_risk": decision["prefer_defined_risk"],
        "allow_directional_buy": decision["allow_directional_buy"],
        "narrative": decision["narrative"],
        "skew_label": decision["skew_label"],
        "raw_score": decision["raw_score"],
        "components": {
            "option_score": decision["components"]["option_score"],
            "tech_score": decision["components"]["tech_score"],
            "premium_score": decision["components"]["premium_score"],
            "total": decision["score"],
            "flow_score": decision["flow_score"],
            "pcr_penalty": decision["pcr_penalty"],
            "gamma_penalty": decision["gamma_penalty"],
            "max_score_cap": decision["max_score_cap"],
            "raw": decision["raw_score"],
        },
        "decision": decision,
    }
