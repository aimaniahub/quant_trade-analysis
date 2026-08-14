OPTION FLOW RADAR – SIGNAL QUALITY FIX REPORT
Date: 13 Aug 2026
Purpose: Detailed diagnosis + complete fix for fake / low-quality strike alerts
Scope: classify_signal(), LIS momentum scoring, strike quality filters

1. Problem Summary
The current Option Flow Radar frequently generates alerts that look active on the option chain, but the underlying stock does not move meaningfully afterward.
Main symptoms:

High LIS score appears
System flags a strike
Stock stays flat or moves opposite
No clear “green” (high-quality) directional outcome

Root cause is not the scanning architecture.
Root cause is the interpretation layer — how OI change + option premium change + option type (CE/PE) are combined.

2. Root Cause Analysis
2.1 classify_signal() is Incomplete and Call-Biased
Current logic mainly understands Call behaviour. Put-side institutional activity is poorly classified.



Actual Market Activity,Correct Label,Current Behaviour
CE OI↑ + CE Premium↑,Fresh Call Buying (Bullish),Mostly handled
CE OI↑ + CE Premium↓,Call Writing (Bearish),Partially handled
PE OI↑ + PE Premium↑,Fresh Put Buying (Bearish),Often becomes Neutral / Weak
PE OI↑ + PE Premium↓,Put Writing (Bullish),Not clearly handled
OI↓ + Premium↑,Short Covering / Unwind,Partially handled
OI↓ + Premium↓,Long Unwinding,Partially handled




































Actual Market ActivityCorrect LabelCurrent BehaviourCE OI↑ + CE Premium↑Fresh Call Buying (Bullish)Mostly handledCE OI↑ + CE Premium↓Call Writing (Bearish)Partially handledPE OI↑ + PE Premium↑Fresh Put Buying (Bearish)Often becomes Neutral / WeakPE OI↑ + PE Premium↓Put Writing (Bullish)Not clearly handledOI↓ + Premium↑Short Covering / UnwindPartially handledOI↓ + Premium↓Long UnwindingPartially handled
Because of this, many real Put flows are under-scored or mislabeled, and some average Call flows get over-scored.
2.2 LIS Momentum Scoring is Call-Centric
Current code:
Pythonmomentum_score = min(max(option_price_change_pct, 0.0) / 5.0, 1.0) * 15.0
Problems:

Only positive option price change is rewarded.
For Puts, rising premium is a bearish signal, but the score treats it the same as Calls.
Falling Put premium (writing) is not properly rewarded as bullish support.

Result: LIS becomes high even when the flow type does not support a strong directional move in the stock.
2.3 Weak Strike Quality Filters

Strikes far from ATM (low delta) can still score high.
No hard requirement that premium direction must match the intended signal type.
Volume spike + OI spike alone are not enough if the activity is writing instead of buying (or vice versa).


3. Solution Overview
Three changes are required:

Rewrite classify_signal() with a complete CE/PE matrix.
Fix LIS momentum scoring so it respects option type.
Tighten strike selection filters (ATM distance + premium direction match).


4. Corrected Classification Logic
Replace the existing classify_signal function with the following logic:
Pythondef classify_signal(
    oi_change_pct: float,
    option_price_change_pct: float,
    underlying_price_change_pct: float,
    opt_type: str,          # "CE" or "PE"
) -> Dict[str, str]:
    """
    Professional OI × Premium × Option Type matrix.
    """
    oi_up = oi_change_pct > 5
    oi_dn = oi_change_pct < -5
    pr_up = option_price_change_pct > 1.5
    pr_dn = option_price_change_pct < -1.5

    # ── CALL side ──────────────────────────────────────────────
    if opt_type == "CE":
        if oi_up and pr_up:
            return {
                "signal": "STRONG_BULLISH",
                "label": "Fresh Call Buying",
                "icon": "🟢",
                "color": "emerald",
                "direction": "BULLISH"
            }
        elif oi_up and pr_dn:
            return {
                "signal": "BEARISH",
                "label": "Call Writing",
                "icon": "🔴",
                "color": "rose",
                "direction": "BEARISH"
            }
        elif oi_dn and pr_up:
            return {
                "signal": "EXHAUSTION",
                "label": "Call Short Covering",
                "icon": "🟡",
                "color": "amber",
                "direction": "BULLISH"
            }
        elif oi_dn and pr_dn:
            return {
                "signal": "EXHAUSTION",
                "label": "Call Long Unwinding",
                "icon": "🔴",
                "color": "rose",
                "direction": "BEARISH"
            }

    # ── PUT side ───────────────────────────────────────────────
    if opt_type == "PE":
        if oi_up and pr_up:
            return {
                "signal": "STRONG_BEARISH",
                "label": "Fresh Put Buying",
                "icon": "🔴",
                "color": "rose",
                "direction": "BEARISH"
            }
        elif oi_up and pr_dn:
            return {
                "signal": "BULLISH",
                "label": "Put Writing",
                "icon": "🟢",
                "color": "emerald",
                "direction": "BULLISH"
            }
        elif oi_dn and pr_up:
            return {
                "signal": "EXHAUSTION",
                "label": "Put Short Covering",
                "icon": "🟡",
                "color": "amber",
                "direction": "BEARISH"
            }
        elif oi_dn and pr_dn:
            return {
                "signal": "EXHAUSTION",
                "label": "Put Long Unwinding",
                "icon": "🟢",
                "color": "emerald",
                "direction": "BULLISH"
            }

    # Fallback
    if oi_up:
        return {
            "signal": "ACCUMULATION",
            "label": "Smart Money Accum.",
            "icon": "🔵",
            "color": "blue",
            "direction": "NEUTRAL"
        }

    return {
        "signal": "NEUTRAL",
        "label": "Neutral/Inconclusive",
        "icon": "⚪",
        "color": "zinc",
        "direction": "NEUTRAL"
    }

5. Corrected LIS Momentum Scoring
Replace the momentum part of compute_lis_v2 with type-aware scoring:
Pythondef compute_momentum_score(option_price_change_pct: float, opt_type: str) -> float:
    """
    Rewards premium movement in the correct directional sense.
    - For CE: rising premium is bullish
    - For PE: rising premium is bearish
    """
    if opt_type == "CE":
        # Rising CE premium = bullish
        return min(max(option_price_change_pct, 0.0) / 5.0, 1.0) * 15.0
    elif opt_type == "PE":
        # Rising PE premium = bearish (still valuable signal)
        return min(max(option_price_change_pct, 0.0) / 5.0, 1.0) * 15.0
    return 0.0
Optional stronger version (recommended):
Pythondef compute_momentum_score(option_price_change_pct: float, opt_type: str, signal_direction: str) -> float:
    """
    Only reward premium movement that agrees with the classified direction.
    """
    if signal_direction == "BULLISH" and opt_type == "CE" and option_price_change_pct > 0:
        return min(option_price_change_pct / 5.0, 1.0) * 15.0
    if signal_direction == "BEARISH" and opt_type == "PE" and option_price_change_pct > 0:
        return min(option_price_change_pct / 5.0, 1.0) * 15.0
    if signal_direction == "BEARISH" and opt_type == "CE" and option_price_change_pct < 0:
        return min(abs(option_price_change_pct) / 5.0, 1.0) * 12.0   # Call writing
    if signal_direction == "BULLISH" and opt_type == "PE" and option_price_change_pct < 0:
        return min(abs(option_price_change_pct) / 5.0, 1.0) * 12.0   # Put writing
    return 0.0

6. Additional Hard Filters (Strike Quality)
Add these filters inside _process_option_chain before scoring:
Python# 1. Prefer strikes closer to ATM (higher delta = more stock impact)
MAX_ATM_DISTANCE_PCT = 7.0          # reject > 7% away
if atm_dist_pct > MAX_ATM_DISTANCE_PCT:
    continue

# 2. Require minimum volume spike
MIN_VOL_SPIKE = 1.5                 # raise from 1.2 to 1.5
if vol_3day_avg > 0 and vol_spike_ratio < MIN_VOL_SPIKE:
    continue

# 3. Require meaningful OI change
MIN_OI_CHANGE = 8.0                 # raise from 5% to 8%
if abs(oi_change_pct) < MIN_OI_CHANGE:
    continue

7. Updated Conviction Logic
Pythondef get_conviction(lis: float, signal_type: str, vol_spike_ratio: float, direction: str) -> Dict[str, str]:
    high_vol = vol_spike_ratio >= 2.0
    strong_signals = ("STRONG_BULLISH", "STRONG_BEARISH", "ACCUMULATION")

    if lis >= 70 and signal_type in strong_signals and high_vol:
        return {"level": "HIGH", "icon": "🔴", "label": "High Conviction"}
    elif lis >= 50 and signal_type in strong_signals:
        return {"level": "MEDIUM", "icon": "🟡", "label": "Medium"}
    elif lis >= 40:
        return {"level": "MEDIUM", "icon": "🟡", "label": "Medium"}
    else:
        return {"level": "LOW", "icon": "⚪", "label": "Low"}

8. Expected Improvement After Fix









Before FixAfter FixMany alerts with no stock follow-throughFewer alerts, higher qualityPut buying often misclassifiedCorrectly labelled as BearishCall writing sometimes over-scoredProperly labelled BearishFar OTM strikes appearingMostly near-ATM strikes onlyHigh LIS on weak directional flowLIS only high when direction is clear



















Before FixAfter FixMany alerts with no stock follow-throughFewer alerts, higher qualityPut buying often misclassifiedCorrectly labelled as BearishCall writing sometimes over-scoredProperly labelled BearishFar OTM strikes appearingMostly near-ATM strikes onlyHigh LIS on weak directional flowLIS only high when direction is clear

9. Implementation Order (Recommended)

Replace classify_signal() with the new version (Section 4).
Update momentum scoring inside compute_lis_v2 (Section 5).
Add the three hard filters (ATM distance, higher vol spike, higher OI change).
Update get_conviction().
Test on 20–30 recent alerts and compare quality.


10. Final Note
The scanning engine (one best strike, 3-day volume baseline, batch processing) is fine.
The problem is almost entirely in how the signal is interpreted.
Once classification and scoring respect the difference between Call and Put behaviour, the number of fake alerts should drop significantly and the remaining alerts will have much higher follow-through probability.