# OPTION CHAIN ANALYZER – Logic Fix & Scoring Hardening Report

**Prepared for AI IDE Integration**  
**Date:** 12 Aug 2026

---

## 1. PURPOSE OF THIS REPORT

This document captures all identified logic flaws, conflicting signal handling issues, and the corrected decision flow for the Option Chain Analyzer. It is designed to be fed directly into an AI IDE / coding agent so the scoring engine, priority order, and action rules can be fixed accurately.

---

## 2. PROBLEMS IDENTIFIED (From Live Output – LICHSGFIN)

### Observed Output Summary
- Spot ₹502 | ATM 500 | Score 60.5 → MEDIUM · BULLISH
- Narrative: Call Long Buildup (HIGH) + Put Short Covering tilt
- Recommendation: BUY ONLY (450 CE / 500 CE)
- OI PCR 0.66 → CALL_WRITING_CEILING
- Volume PCR 0.39 → BEARISH
- HTF Daily: BEARISH
- 15m stack: MIXED
- Gamma Wall @ 500: BEARISH
- IV Skew: 0.0 (FLAT)
- Max Pain: 510 | Put Wall 500 | Call Wall 520
- Signals still showing WAIT in places, but overall bias forced BULLISH

### Core Issues
1. **Over-weighting of single Long Buildup signal** — Fresh Call Long Buildup was allowed to dominate even when structural ceiling (low OI PCR), higher-timeframe trend, and Gamma wall were all opposing.
2. **Missing hard filters** — HTF BEARISH and OI PCR < 0.70 should have capped the maximum possible score and forced a WAIT or NEUTRAL stance.
3. **Flat IV Skew treated neutrally** — A flat skew (0.0) should give **zero directional edge**, not be ignored. It removes any volatility confirmation.
4. **Conflicting signals not producing clear WAIT** — System still recommended BUY ONLY despite multiple high-weight bearish structural factors.
5. **No penalty for Volume PCR extreme** — Volume PCR 0.39 (very low) indicates aggressive call activity that often precedes resistance, yet it was not heavily penalised.

---

## 3. ROOT CAUSE ANALYSIS

The current engine treats **Buildup Classification** as the primary (almost sole) driver of bias. In professional quant systems, Buildup is only one layer. Structure (PCR + Gamma + Max Pain) and Higher Timeframe Gate must sit above pure flow. When flow and structure conflict, the system must default to WAIT or defined-risk only, never aggressive directional BUY.

---

## 4. CORRECTED PRIORITY ORDER (Non-Negotiable)

| # | Layer                        | Role                          | Action if Conflict                          |
|---|------------------------------|-------------------------------|---------------------------------------------|
| 1 | HTF Gate (Daily / 4H)        | Hard directional filter       | Cap max score + force side preference       |
| 2 | OI PCR + Volume PCR          | Structural ceiling / floor    | Heavy penalty if Call Writing Ceiling       |
| 3 | Buildup + Strength           | Flow quality (fresh money)    | Reward only if confirmed by structure       |
| 4 | Gamma Wall + Max Pain        | Mechanical pressure zones     | Penalty if Gamma Wall BEARISH near spot     |
| 5 | IV Skew + Premium Behaviour  | Volatility confirmation       | Flat skew = zero edge (no bonus)            |
| 6 | 15-min Technical Stack       | Timing / entry trigger        | MIXED or opposing = reduce tech score       |
| 7 | Final Score + Action Rules   | Conviction + recommended side | Default to WAIT on conflict                 |

---

## 5. FULL CORRECTED LOGIC FLOW (Implementation Spec)

```python
def get_final_bias_and_score(data):
    # data keys expected:
    # htf_daily, oi_pcr, vol_pcr, atm_pcr, atm_call_buildup, atm_put_buildup,
    # buildup_strength, gamma_wall, gamma_bias, max_pain, spot,
    # iv_skew, straddle_change_pct, tech_15m, volume_vs_avg

    # ----- 1. HTF GATE (Hard Filter) -----
    htf = data['htf_daily']          # "BULLISH" | "BEARISH" | "NEUTRAL"
    if htf == "BEARISH":
        max_score = 58
        side_pref = "SHORT_PREFERRED" if data['oi_pcr'] < 0.75 else "NEUTRAL"
    elif htf == "BULLISH":
        max_score = 92
        side_pref = "LONG_PREFERRED"
    else:
        max_score = 75
        side_pref = "NEUTRAL"

    # ----- 2. PCR REGIME -----
    oi_pcr = data['oi_pcr']
    vol_pcr = data['vol_pcr']
    pcr_penalty = 0
    if oi_pcr < 0.70:
        pcr_regime = "CALL_WRITING_CEILING"
        pcr_penalty = 12
    elif oi_pcr > 1.25:
        pcr_regime = "PUT_WRITING_FLOOR"
        pcr_penalty = -8          # bonus
    else:
        pcr_regime = "BALANCED"
        pcr_penalty = 0

    if vol_pcr < 0.45:
        pcr_penalty += 6          # aggressive call activity today

    # ----- 3. BUILDUP QUALITY -----
    call_bu = data['atm_call_buildup']
    put_bu  = data['atm_put_buildup']
    strength = data['buildup_strength']   # HIGH / MEDIUM / WEAK

    if call_bu == "Long Buildup" and strength == "HIGH":
        flow_score = 28
        narrative = "Call Long Buildup (HIGH)"
    elif call_bu == "Long Buildup":
        flow_score = 18
        narrative = "Call Long Buildup (Moderate)"
    elif put_bu == "Short Covering":
        flow_score = 14
        narrative = "Put Short Covering only"
    else:
        flow_score = 8
        narrative = "No clear directional flow"

    # Bonus only when both sides confirm
    if call_bu == "Long Buildup" and put_bu in ["Short Covering", "Long Unwinding"]:
        flow_score += 6
        narrative += " + Put support"

    # ----- 4. GAMMA + MAX PAIN -----
    gamma_penalty = 0
    if abs(data['gamma_wall'] - data['spot']) < (data['spot'] * 0.008):
        if data['gamma_bias'] == "BEARISH":
            gamma_penalty = 7
        elif data['gamma_bias'] == "BULLISH":
            gamma_penalty = -5

    max_pain_bonus = 4 if data['spot'] < data['max_pain'] else -3

    # ----- 5. IV SKEW + PREMIUM -----
    iv_skew = data['iv_skew']          # Put IV - Call IV (or your signed formula)
    if iv_skew > 3.5:
        skew_score = 6
    elif iv_skew < -2.0:
        skew_score = -5
    else:
        skew_score = 0                 # FLAT → zero edge

    straddle_chg = data['straddle_change_pct']
    if straddle_chg > 4:
        premium_score = 14
    elif straddle_chg > 0:
        premium_score = 9
    else:
        premium_score = 5

    # ----- 6. 15-min TECHNICAL -----
    tech = data['tech_15m']            # BULLISH / MIXED / BEARISH
    vol_ratio = data['volume_vs_avg']
    if tech == "BULLISH" and vol_ratio > 1.1:
        tech_score = 28
    elif tech == "BULLISH":
        tech_score = 20
    elif tech == "MIXED":
        tech_score = 12
    else:
        tech_score = 6

    # ----- FINAL SCORE -----
    raw = (flow_score + tech_score + premium_score + skew_score
           + max_pain_bonus - pcr_penalty - gamma_penalty)
    final = max(min(raw, max_score), 15)

    # ----- ACTION RULES -----
    if final >= 72 and side_pref == "LONG_PREFERRED":
        action, conviction = "BUY", "HIGH"
    elif final >= 62 and side_pref != "SHORT_PREFERRED":
        action, conviction = "BUY_CAUTIOUS", "MEDIUM"
    elif final <= 42 and side_pref == "SHORT_PREFERRED":
        action, conviction = "SELL", "MEDIUM-HIGH"
    else:
        action, conviction = "WAIT", "LOW / CONFLICTED"

    return {
        "score": round(final, 1),
        "action": action,
        "conviction": conviction,
        "narrative": narrative,
        "pcr_regime": pcr_regime,
        "side_preference": side_pref,
        "max_score_cap": max_score
    }
```

---

## 6. SPECIFIC FIXES TO IMPLEMENT

### 6.1 Low OI PCR / Call Writing Ceiling
- If OI PCR < 0.70 → set regime = CALL_WRITING_CEILING and apply –12 point penalty.
- If Volume PCR also < 0.45 → add extra –6.
- This must override pure Long Buildup enthusiasm.

### 6.2 Higher Timeframe (HTF) Gate
- HTF BEARISH → hard cap maximum score at 58 and set side_preference = SHORT_PREFERRED (or NEUTRAL if PCR is not also low).
- HTF BULLISH → allow up to 92.
- Never allow a full BUY recommendation against a clear HTF bearish bias.

### 6.3 Flat IV Skew Handling
- When |IV Skew| is near zero (e.g. between –2.0 and +3.5) → skew_score = 0.
- Explicitly label the setup as “No Volatility Edge”.
- Prefer defined-risk structures (spreads) over naked options when skew is flat.

### 6.4 Gamma Wall Conflict
- If Gamma Wall is within 0.8% of spot AND labelled BEARISH → apply –7 penalty.
- This captures dealer short-gamma pressure at ATM.

### 6.5 Dual-Side Confirmation Bonus
- Full flow credit (extra +6) only when Call side shows Long Buildup **AND** Put side shows Short Covering or Long Unwinding.
- Single-side Long Buildup alone is weaker.

### 6.6 Action Rules (Strict)
- Score ≥ 72 **and** side_pref = LONG_PREFERRED → BUY (HIGH)
- Score ≥ 62 and not SHORT_PREFERRED → BUY_CAUTIOUS (MEDIUM)
- Score ≤ 42 and SHORT_PREFERRED → SELL
- Everything else → **WAIT** (LOW / CONFLICTED)

---

## 7. EXPECTED BEHAVIOUR AFTER FIX (LICHSGFIN Case)

| Factor                      | Old Behaviour                  | New Correct Behaviour                  |
|-----------------------------|--------------------------------|----------------------------------------|
| Long Buildup HIGH           | Dominated score → 60.5 BULLISH | Still rewarded, but heavily capped     |
| OI PCR 0.66                 | Mostly ignored                 | CALL_WRITING_CEILING → –12 pts         |
| Vol PCR 0.39                | Light penalty                  | Extra –6 pts                           |
| HTF BEARISH                 | Not enforced                   | Hard cap max score = 58                |
| Gamma Wall BEARISH @500     | Noted but weak impact          | –7 pts penalty                         |
| IV Skew = 0.0               | Ignored                        | skew_score = 0 (no edge)               |
| Final Action                | BUY ONLY                       | WAIT / LOW-MEDIUM (Conflicted)         |

---

## 8. RECOMMENDED CLEAN OUTPUT FORMAT

```
Score          : 51.5 – 54.0
Action         : WAIT
Conviction     : LOW (Conflicted)
Primary Flow   : Call Long Buildup (HIGH)
Structure      : CALL_WRITING_CEILING (OI PCR 0.66)
HTF            : BEARISH  →  max score capped at 58
Gamma          : BEARISH wall at 500
IV Skew        : FLAT → No Volatility Edge
15m            : MIXED
Premium        : Stable (no expansion)

Verdict: Fresh bullish flow exists but is fighting a strong call-writing 
ceiling + higher-timeframe bearish bias. Wait for either ceiling break 
or clear HTF turn before directional entry.
```

---

## 9. IMPLEMENTATION CHECKLIST FOR AI IDE

1. Replace the existing scoring function with the `get_final_bias_and_score()` logic above.
2. Add hard HTF gate that sets `max_score` and `side_preference` before any other calculation.
3. Implement OI PCR < 0.70 → CALL_WRITING_CEILING with –12 penalty (+ extra –6 if Vol PCR < 0.45).
4. Force `skew_score = 0` when IV Skew is flat (between –2.0 and +3.5).
5. Add Gamma Wall proximity check (within 0.8% of spot) and apply ± penalty.
6. Grant dual-side confirmation bonus (+6) only when both Call Long Buildup and Put support exist.
7. Change final action rules so that conflicting signals default to WAIT.
8. Update the UI / print layer to show the new fields: `pcr_regime`, `side_preference`, `max_score_cap`, verdict text.
9. Add unit tests for the LICHSGFIN-style conflict case to ensure score stays ≤ 58 and action = WAIT.
10. Document the new priority order in code comments so future changes respect the hierarchy.

---

## 10. FINAL NOTE

The goal is **not** to eliminate Long Buildup signals.  
The goal is to prevent a single positive flow signal from overriding structural and higher-timeframe opposition. When flow and structure disagree, professional systems stand aside (WAIT) or use only defined-risk structures. This report encodes that discipline.

---

*Option Chain Analyzer – Logic Fix Report | Generated for AI IDE consumption*
