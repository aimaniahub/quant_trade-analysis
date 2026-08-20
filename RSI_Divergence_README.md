# RSI Divergence Desk — Complete Specification

**Status:** Research + Implementation Spec  
**Date:** 19 Aug 2026  
**Scope:** RSI Bullish & Bearish Divergence for F&O stocks  
**Related Systems:** Option Chain Permission, Multi-Timeframe Gate, 15m/1H RSI Extreme Desk  

---

## 0. One-Line Product Summary

> Detect when price and RSI move in opposite directions (divergence), then only promote the signal when higher-timeframe context + option-chain sponsorship agree. Divergence is a **momentum exhaustion warning**, not a standalone buy/sell button.

---

## 1. What is RSI Divergence?

RSI Divergence occurs when **price** and **RSI** make opposite swing patterns.

| Type              | Price Action     | RSI Action      | Meaning                                      | Bias     |
|-------------------|------------------|-----------------|----------------------------------------------|----------|
| **Bullish Div**   | Lower Low        | Higher Low      | Selling pressure is weakening                | Long     |
| **Bearish Div**   | Higher High      | Lower High      | Buying pressure is weakening                 | Short    |

### Visual Example (from live charts)

- Price prints a new low  
- RSI refuses to make a new low (makes a higher low instead)  
→ **Bullish Divergence** is marked

This is the classic “momentum is diverging from price” signal.

---

## 2. Why Divergence Matters (and Why It Fails Alone)

### Strengths
- Early warning that the current impulse is losing strength
- Works well near oversold/overbought zones
- Good confluence tool when combined with structure and options flow

### Weaknesses (Critical)
- Divergence can persist for many bars in strong trends
- Many false signals in choppy or low-volume markets
- Buying every Bullish Divergence is a losing strategy (proven in large sample backtests)

**Conclusion:**  
Divergence is a **confirmation / boost layer**, never the primary trigger.

---

## 3. Core Philosophy for This Desk

```
Divergence alone     →  WATCH or IGNORE
Divergence + RSI extreme (≤35 / ≥65) + Reclaim + Option Chain agrees + HTF allows
                     →  TRADE candidate
```

We treat divergence the same way we treat RSI ≤ 30:
- It shows **location of exhaustion**
- Real money (option chain) decides if a reversal is sponsored
- Higher timeframe decides if we are allowed to take the side

---

## 4. Detection Logic

### 4.1 Required Components

1. **Swing / Pivot Detection** on both Price and RSI
2. Comparison of the last two significant pivots
3. Confirmation that the pivots are valid (minimum bars between them)

### 4.2 Bullish Divergence Rules

```text
Condition A: Price makes a Lower Low (LL)
Condition B: RSI makes a Higher Low (HL) at the corresponding pivots
Condition C: Minimum 5–8 bars between the two pivots (avoid noise)
Condition D: The second RSI low is still in or near oversold territory (preferably ≤ 40)
```

### 4.3 Bearish Divergence Rules

```text
Condition A: Price makes a Higher High (HH)
Condition B: RSI makes a Lower High (LH)
Condition C: Minimum bars between pivots
Condition D: Second RSI high is still elevated (preferably ≥ 60)
```

### 4.4 Pivot Detection (Recommended Settings)

| Parameter              | Value          | Reason                              |
|------------------------|----------------|-------------------------------------|
| Left bars              | 3–5            | Confirmed swing                     |
| Right bars             | 2–3            | Avoid repainting too much           |
| Minimum pivot distance | 5 bars         | Filter micro noise                  |
| RSI Period             | 14 (Wilder)    | Standard                            |

---

## 5. Multi-Timeframe Hierarchy

| Timeframe | Role                              | Power     |
|-----------|-----------------------------------|-----------|
| **1H**    | Regime filter                     | Highest   |
| **15m**   | Primary divergence trigger        | Primary   |
| **5m**    | Early warning only                | Lowest    |

### Priority Ranking

| Priority | Condition                                      | Action          |
|----------|------------------------------------------------|-----------------|
| A        | 15m + 1H both show same divergence             | Strongest       |
| B        | 15m divergence + 1H not opposed                | Good            |
| C        | Only 15m divergence                            | Watch           |
| D        | Only 5m divergence                             | Ignore / Early  |

---

## 6. Integration with Existing Systems

### 6.1 With RSI Extreme Desk

Divergence should boost the Extreme Score:

```text
+15 points  →  Bullish/Bearish Divergence present on 15m
+10 points  →  Also present on 1H
+5 points   →  Divergence occurs while RSI is ≤ 35 or ≥ 65
```

### 6.2 With Option Chain Permission

| Divergence Type     | Required OC Permission          | Result                  |
|---------------------|---------------------------------|-------------------------|
| Bullish Div         | Bullish (PE writing / CE LB)    | TRADE long candidate    |
| Bullish Div         | Bearish or Conflict             | REJECT / Knife          |
| Bearish Div         | Bearish (CE writing / PE LB)    | TRADE short candidate   |
| Bearish Div         | Bullish or Conflict             | REJECT                  |

### 6.3 With 4H Allowed Side

- Bullish Divergence + 4H firmly SHORT → **No long ticket**
- Bearish Divergence + 4H firmly LONG → **No short ticket**

Same hard gate used in the 7/200 and RSI Extreme desks.

---

## 7. Event Classification

Every detected divergence should be tagged with an event type:

| Event Tag       | Meaning                                      |
|-----------------|----------------------------------------------|
| `BULL_DIV`      | Classic bullish divergence                   |
| `BEAR_DIV`      | Classic bearish divergence                   |
| `BULL_DIV_FRESH`| Divergence just completed this bar / last bar|
| `BEAR_DIV_FRESH`| Same for bearish                             |
| `DIV_STALE`     | Divergence is old (> 6–8 bars ago)           |

Fresh divergences carry higher weight.

---

## 8. Scoring Model (Suggested)

```text
Divergence Score (D) = 0–100

Base:
+ 40  if valid 15m divergence
+ 25  if 1H also confirms
+ 15  if RSI is in extreme zone (≤35 / ≥65)
+ 10  if Fresh (just formed)
+ 10  if price is near support/resistance or VWAP

Final Desk Score = 
  0.35 × Extreme Score (E)
+ 0.25 × Divergence Score (D)
+ 0.40 × Permission Score (P)
```

Permission remains the heaviest component.

---

## 9. Board Logic (TRADE / WATCH / REJECT)

| Condition                                      | Board     |
|------------------------------------------------|-----------|
| Valid Div + Extreme + Reclaim + OC agrees + 4H allows | **TRADE** |
| Valid Div + Extreme + OC agrees but no reclaim yet   | **WATCH** |
| Valid Div but OC conflicts or 4H veto                | **REJECT**|
| Divergence alone (RSI 40–60)                         | **IGNORE**|

---

## 10. Implementation Plan

### Phase 1 — Detection Engine
- Create `detect_pivots(candles, left=4, right=2)`
- Create `detect_bullish_divergence(price_pivots, rsi_pivots)`
- Create `detect_bearish_divergence(...)`
- Return structured event: `{type, strength, bars_ago, rsi_at_pivot, price_at_pivot}`

### Phase 2 — Integration
- Hook into existing `rsi_desk.py`
- Add divergence boost to scoring
- Pass divergence tag into the ticket builder

### Phase 3 — UI
- Show badge: `BULL DIV` / `BEAR DIV`
- Colour code: Green for bullish, Red for bearish
- Tooltip showing pivot values and bars ago

### Phase 4 — Filters (Optional)
- Minimum volume filter
- Only show if divergence occurs near VWAP / EMA20
- Divergence strength filter (RSI difference > X points)

---

## 11. Recommended Default Settings

| Setting                        | Value          | Notes                          |
|--------------------------------|----------------|--------------------------------|
| RSI Period                     | 14             | Wilder smoothing               |
| Pivot Left / Right             | 4 / 2          | Balance between noise & lag    |
| Min bars between pivots        | 5              | Avoid micro swings             |
| RSI zone preference            | ≤ 38 / ≥ 62    | Slightly wider than classic 30/70 |
| Fresh window                   | ≤ 3 bars       | High priority                  |
| Stale after                    | 8 bars         | Demote                         |

---

## 12. Risks & How to Handle Them

| Risk                              | Mitigation                                      |
|-----------------------------------|-------------------------------------------------|
| Too many weak divergences         | Require minimum RSI difference + volume         |
| Divergence in strong trend        | 4H hard gate + ADX filter (optional)            |
| Repainting pivots                 | Use confirmed right-side bars                   |
| Over-fitting on 5m                | Keep 5m as early warning only                   |
| Users treating Div as buy signal  | Force OC + HTF gates in the UI copy             |

---

## 13. Example Ticket (Bullish Divergence)

```text
Symbol:       COALINDIA
Side:         LONG
Trigger:      Bullish Divergence on 15m + RSI reclaim 31.4
RSI 15m:      29.8 → 33.1
RSI 1H:       34.2 (not opposed)
Event:        BULL_DIV_FRESH
Permission:   PE Writing @ 400 + Futures Long Buildup
4H Gate:      Allowed LONG
Vehicle:      410 CE  or  410/430 Call Spread
Stop:         Below recent swing low / Put Wall
Target 1:     VWAP → Call Wall
Time Stop:    RSI must hold above 40 within 4–5 bars
Invalidation: OC flips to PE Long Buildup or 4H turns firmly SHORT
```

---

## 14. What This Desk is NOT

- It is **not** a pure divergence scanner that dumps every Div signal
- It is **not** a replacement for the RSI Extreme desk
- It does **not** override Option Chain or 4H permission
- It does **not** require a new data harvest loop (uses existing 15m history)

---

## 15. Final Product Rule

> **Divergence tells us that momentum is shifting.  
> Option Chain tells us whether anyone is willing to pay for that shift.  
> Higher Timeframe tells us whether we are allowed to take the trade.**

Only when all three align do we print a TRADE ticket.

---

## 16. Suggested Build Order

1. Pivot + Divergence detection functions
2. Event tagging (`BULL_DIV`, `BEAR_DIV`, `FRESH`)
3. Score boost integration
4. UI badge + tooltip
5. Optional strength & volume filters

---

*End of RSI Divergence Specification*