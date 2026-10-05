"""
Signal Interpreter & Human Narrative Engine
============================================
Translates raw quant/F&O option chain metrics into human-readable sentences,
regime labels, color codes, and score-based AI+Chain news fusion.
"""

from typing import Any, Dict, List, Optional, Tuple


def interpret_pcr(
    oi_pcr: Optional[float],
    vol_pcr: Optional[float] = None,
    atm_pcr: Optional[float] = None,
    spot: float = 0.0,
    max_pain: Optional[float] = None,
) -> Dict[str, Any]:
    if oi_pcr is None or oi_pcr <= 0:
        return {
            "regime": "UNKNOWN",
            "label": "No PCR Data",
            "sentence": "PCR unavailable for this symbol.",
            "color": "zinc",
            "bias": "NEUTRAL",
        }

    pcr = float(oi_pcr)
    if pcr >= 1.4:
        regime = "HEAVY_PUT_FLOOR"
        label = "Put Writing Floor (Strong Bullish)"
        sentence = f"OI PCR {pcr:.2f} — Heavy Put writing creating strong support floor."
        color = "emerald"
        bias = "BULLISH"
    elif pcr >= 1.15:
        regime = "PUT_LEAN"
        label = "Put Support (Mild Bullish)"
        sentence = f"OI PCR {pcr:.2f} — Put writing dominating Calls, support holding."
        color = "emerald"
        bias = "BULLISH"
    elif pcr >= 0.85:
        regime = "BALANCED"
        label = "Balanced PCR (Range-bound)"
        sentence = f"OI PCR {pcr:.2f} — Equal Call and Put interest, neutral bounds."
        color = "amber"
        bias = "NEUTRAL"
    elif pcr >= 0.65:
        regime = "CALL_LEAN"
        label = "Call Resistance (Mild Bearish)"
        sentence = f"OI PCR {pcr:.2f} — Call writing creating overhead resistance."
        color = "rose"
        bias = "BEARISH"
    else:
        regime = "CALL_WRITING_CEILING"
        label = "Call Writing Ceiling (Strong Bearish)"
        sentence = f"OI PCR {pcr:.2f} — Heavy Call writing capping upside move."
        color = "rose"
        bias = "BEARISH"

    # Contextual adjustments
    if vol_pcr is not None and float(vol_pcr) > 0:
        vpcr = float(vol_pcr)
        if pcr > 1.1 and vpcr < 0.6:
            sentence += f" (Note: Intraday Volume PCR {vpcr:.2f} shows active Call volume)"
        elif pcr < 0.8 and vpcr > 1.3:
            sentence += f" (Note: Intraday Volume PCR {vpcr:.2f} shows active Put volume)"

    return {
        "regime": regime,
        "label": label,
        "sentence": sentence,
        "color": color,
        "bias": bias,
        "pcr": round(pcr, 2),
    }


def interpret_iv_skew(skew: Optional[float], skew_label: Optional[str] = None) -> Dict[str, Any]:
    if skew is None:
        return {
            "label": "FLAT",
            "sentence": "IV Skew unavailable.",
            "color": "zinc",
            "implication": "No volatility edge",
        }

    sk = float(skew)
    if sk > 3.5:
        return {
            "label": "PUT_SKEW_HIGH",
            "sentence": f"IV Skew +{sk:.1f}% — OTM Puts expensive (High Downside Protection / Fear)",
            "color": "rose",
            "implication": "Market paying up for downside put protection. Watch for support test.",
        }
    elif sk > 1.5:
        return {
            "label": "PUT_SKEW_MILD",
            "sentence": f"IV Skew +{sk:.1f}% — Put premium slightly higher than Call",
            "color": "amber",
            "implication": "Mild downside demand. Standard protection regime.",
        }
    elif sk < -3.5:
        return {
            "label": "CALL_SKEW_HIGH",
            "sentence": f"IV Skew {sk:.1f}% — OTM Calls expensive (High Bullish Speculation)",
            "color": "emerald",
            "implication": "Bulls paying high premium for call upside. Expect violent momentum.",
        }
    elif sk < -1.5:
        return {
            "label": "CALL_SKEW_MILD",
            "sentence": f"IV Skew {sk:.1f}% — Call premium higher than Put",
            "color": "emerald",
            "implication": "Mild upside bias in option pricing.",
        }
    else:
        return {
            "label": "FLAT_SKEW",
            "sentence": f"IV Skew {sk:.1f}% — Symmetrical volatility smile across strikes",
            "color": "zinc",
            "implication": "No volatility skew edge. Spreads preferred over naked options.",
        }


def interpret_buildup(
    state: Optional[str],
    strength: Optional[str] = None,
    dual_confirm: bool = False,
) -> Dict[str, Any]:
    st = (state or "").lower()
    str_val = (strength or "MEDIUM").upper()

    if "long buildup" in st:
        icon = "🟢"
        if str_val in ("HIGH", "STRONG"):
            sentence = "Strong Fresh Long Buying — Smart money accumulating upside positions."
            badge = "🟢 STRONG LONG"
            color = "emerald"
        else:
            sentence = "Moderate Long Buildup — Fresh buyers entering call contracts."
            badge = "🟢 LONG BUILDUP"
            color = "emerald"
    elif "short buildup" in st:
        icon = "🔴"
        if str_val in ("HIGH", "STRONG"):
            sentence = "Strong Short Buildup — Fresh short selling / Call writing dominating."
            badge = "🔴 STRONG SHORT"
            color = "rose"
        else:
            sentence = "Short Buildup — Short positions opening across key strikes."
            badge = "🔴 SHORT BUILDUP"
            color = "rose"
    elif "short covering" in st:
        icon = "🟡"
        sentence = "Short Covering Rally — Short sellers exiting, causing momentum pop."
        badge = "🟡 SHORT COVER"
        color = "amber"
    elif "long unwinding" in st:
        icon = "🟧"
        sentence = "Long Unwinding — Long positions exiting, downward pressure without fresh shorts."
        badge = "🟧 LONG UNWIND"
        color = "orange"
    else:
        icon = "⚪"
        sentence = "Churn / Neutral Buildup — No distinct directional accumulation."
        badge = "⚪ CHURN"
        color = "zinc"

    if dual_confirm:
        sentence += " (Confirmed by opposing Put side support)"

    return {
        "badge": badge,
        "sentence": sentence,
        "icon": icon,
        "color": color,
        "state": state,
        "strength": str_val,
    }


def compute_news_chain_alignment(pick: Dict[str, Any], chain: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score-based News ↔ Option Chain Fusion (Replacing fragile 4-branch if/else)
    Returns score (0-100), action, reasons list, and conflict note.
    """
    score = 0
    reasons: List[str] = []
    conflict_note: Optional[str] = None

    if chain.get("error") or not chain.get("grade"):
        return {
            "action": "NEWS_ONLY",
            "alignment_score": 20,
            "reasons": ["No option chain data available for validation"],
            "conflict_note": None,
        }

    grade = chain.get("grade")
    chain_bias = (chain.get("chain_bias") or "NEUTRAL").upper()
    news_intent = (pick.get("news_intent") or "UNCLEAR").upper()
    event_type = (pick.get("event_type") or "OTHER").upper()
    repeat_n = int(pick.get("repeat_n") or 1)
    pcr_regime = (chain.get("pcr_regime") or "BALANCED").upper()
    intent = str(chain.get("intent") or "")

    # 1. Chain Grade (0–30 pts)
    if grade == "TRADEABLE":
        score += 30
        reasons.append("Chain Grade: TRADEABLE (+30)")
    elif grade == "WATCH":
        score += 15
        reasons.append("Chain Grade: WATCH (+15)")
    else:
        reasons.append(f"Chain Grade: {grade} (+0)")

    # 2. News ↔ Chain Direction Alignment (0–35 pts)
    if news_intent == "BULLISH" and chain_bias == "BULLISH":
        score += 35
        reasons.append("News (BULLISH) & Chain (BULLISH) aligned (+35)")
    elif news_intent == "BEARISH" and chain_bias == "BEARISH":
        score += 35
        reasons.append("News (BEARISH) & Chain (BEARISH) aligned (+35)")
    elif news_intent == "VOL" and chain.get("explode_state") in ("EARLY", "ACTIVE"):
        score += 25
        reasons.append("Vol Catalyst + Chain Activity (+25)")
    elif chain_bias == "CONFLICTED":
        score -= 10
        reasons.append("Chain is internally conflicted (-10)")
        conflict_note = "Chain technicals & PCR show conflicting signals."
    elif news_intent in ("BULLISH", "BEARISH") and chain_bias != "NEUTRAL" and news_intent != chain_bias:
        score -= 15
        reasons.append(f"Direction Conflict: News {news_intent} vs Chain {chain_bias} (-15)")
        conflict_note = f"News catalyst is {news_intent} but Option Chain structure is {chain_bias}."

    # 3. PCR Regime Confirmation (0–20 pts)
    pcr_bullish = pcr_regime in ("PUT_WRITING_FLOOR", "PUT_LEAN", "HEAVY_PUT_FLOOR")
    pcr_bearish = pcr_regime in ("CALL_WRITING_CEILING", "CALL_LEAN")

    if news_intent == "BULLISH" and pcr_bullish:
        score += 20
        reasons.append("PCR Regime confirms Put Floor (+20)")
    elif news_intent == "BEARISH" and pcr_bearish:
        score += 20
        reasons.append("PCR Regime confirms Call Ceiling (+20)")
    elif pcr_regime == "BALANCED":
        score += 10
        reasons.append("PCR Regime is Balanced (+10)")
    elif news_intent == "BULLISH" and pcr_bearish:
        reasons.append("Warning: PCR indicates Call Ceiling despite bullish news")
        if not conflict_note:
            conflict_note = "Heavy Call writing overhead creates resistance against bullish news."

    # 4. News Quality & Catalyst Strength (0–15 pts)
    if event_type in ("EARNINGS", "ORDER_WIN", "M_AND_A"):
        score += 10
        reasons.append(f"High impact catalyst: {event_type} (+10)")
    elif event_type in ("RATING", "PRODUCT_LAUNCH"):
        score += 5

    if repeat_n >= 3:
        score += 5
        reasons.append(f"Multiple news coverage (×{repeat_n}) (+5)")

    # Final score normalization
    final_score = max(0, min(100, score))

    # Action Thresholds
    if final_score >= 70:
        action = "STRONG_CARD"
    elif final_score >= 50:
        action = "CARD"
    elif final_score >= 30:
        action = "WATCH"
    else:
        action = "NEWS_ONLY"

    return {
        "action": action,
        "alignment_score": final_score,
        "reasons": reasons,
        "conflict_note": conflict_note,
        "news_intent": news_intent,
        "chain_bias": chain_bias,
        "grade": grade,
    }
