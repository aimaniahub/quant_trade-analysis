# OI Cluster Engine — Entry, Target & Exit Specification

**Date:** 14 August 2026  
**Status:** Design complete — ready for implementation  
**Depends on:**  
- Multi-Timeframe Momentum engine (4H → 1H → 15m direction)  
- Option Flow Radar v3 (CE/PE classification, LIS, Greeks, Alert Box)

**Purpose of this document:**  
Define how Open Interest clusters and volume clusters from the option chain are used to set precise **Entry zone**, **Target**, and **Exit / trail triggers**.  

This layer does **not** decide direction.  
Direction is already decided by the MTF engine.  
This layer only answers: *Where to enter, where to take profit, and when the fuel is dying.*

---

## 1. Core Philosophy

```
MTF (4H + 1H + 15m)     →  Decides ALLOWED SIDE and when the idea is alive
Option Flow Radar       →  Decides FUEL QUALITY and unusual activity
OI Cluster Engine       →  Decides ENTRY ZONE, TARGET, and EXIT TRIGGER
```

Key principles:

1. Large OI clusters act as magnets (support / resistance).
2. Fresh building of OI in our direction = sponsorship is alive.
3. Liquidation of the supporting cluster = fuel is fading → tighten or exit.
4. Technical levels (VWAP, Camarilla, Pivots) are secondary confirmation only.
5. Entry and Target must be side-aware (bullish vs bearish logic is opposite).

---

## 2. Definitions

### 2.1 OI Cluster

A strike (or tight group of neighbouring strikes) is considered a meaningful cluster when:

- Absolute OI is significantly higher than the average OI of nearby strikes
- OR the strike shows a clear local peak in OI
- Minimum absolute OI threshold (configurable, e.g. top 20% of chain or fixed floor)

### 2.2 Supporting Cluster vs Opposing Cluster

| Trade Side | Supporting Cluster | Opposing Cluster |
|------------|--------------------|------------------|
| **Bullish** (Long / Buy CE) | Put OI cluster below price (demand) | Call OI cluster above price (supply) |
| **Bearish** (Short / Buy PE) | Call OI cluster above price (supply) | Put OI cluster below price (demand) |

### 2.3 Cluster State

| State | Meaning |
|-------|---------|
| **Building** | OI rising + volume active |
| **Stable** | OI high but little change |
| **Liquidating** | OI falling meaningfully while price moves against the cluster |
| **Fresh** | Large OI added today / recent sessions |

---

## 3. Detection Rules (How to find clusters)

For the current expiry (and optionally next expiry):

1. Take the full option chain (reasonable strike range, e.g. ±10–15% from spot).
2. Identify local OI peaks on both Call and Put side.
3. Rank clusters by:
   - Absolute OI
   - OI change (freshness)
   - Volume at that strike
4. Keep the top 3–5 Call clusters and top 3–5 Put clusters.
5. Mark the nearest supporting and nearest opposing cluster relative to current spot.

**Additional quality filters:**
- Ignore deep OTM clusters with very low delta unless absolute size is extreme.
- Prefer clusters that also have elevated volume (not dead OI).

---

## 4. Entry Zone Rules

### 4.1 Bullish Trade (Allowed side = LONG)

Preferred Entry Zone:
- Near or just above a strong **Put OI cluster** (supporting demand)
- Or on a reclaim of a key Put cluster that was tested
- Secondary: VWAP / Camarilla support only if it aligns with a Put cluster

Avoid entry:
- Directly into a heavy Call OI wall with no supporting Put cluster nearby
- Far from any meaningful Put cluster (no demand base)

### 4.2 Bearish Trade (Allowed side = SHORT)

Preferred Entry Zone:
- Near or just below a strong **Call OI cluster** (supporting supply / resistance)
- Or on rejection from a Call cluster
- Secondary: VWAP / Camarilla resistance only if it aligns with a Call cluster

Avoid entry:
- Directly into a heavy Put OI wall with no Call cluster above
- Far from any meaningful Call cluster

### 4.3 Entry Quality Score (optional)

Give higher entry quality when:
- Price is within 0.5–1.5% of a strong supporting cluster
- The supporting cluster is still Building or Stable (not liquidating)
- Volume is present at that cluster

---

## 5. Target Rules

### 5.1 Primary Target

| Side | Primary Target |
|------|----------------|
| Bullish | Nearest strong **Call OI cluster** above current price |
| Bearish | Nearest strong **Put OI cluster** below current price |

This is the first institutional supply/demand zone the price is likely to react to.

### 5.2 Secondary / Extended Target

- Next cluster beyond the primary one
- Or a major technical level only if it coincides with an OI cluster

### 5.3 Target Validity Check

Before showing a target:
- Confirm the opposing cluster still has meaningful OI
- If the opposing cluster is already heavily liquidating, the target may be weaker → reduce conviction or trail earlier

---

## 6. Exit & Trail Rules (Most Important)

The supporting cluster tells us whether the fuel is still alive.

### 6.1 Exit / Tighten Triggers

| Event | Action |
|-------|--------|
| Supporting cluster starts **liquidating** (OI↓ meaningfully) while price is still in our favour | Tighten stop / trail aggressively |
| Supporting cluster liquidates + price closes back through the cluster | Exit or reduce size significantly |
| Opposing cluster is absorbed (OI falls while price pushes through) | Can trail further / hold for extended target |
| Dual-sided heavy liquidation (both Call and Put OI dropping fast) | Stand aside / exit — volatility event, no clear sponsorship |
| MTF invalidation (1H or 4H break) | Exit regardless of clusters |

### 6.2 Hard Rule

> Never ignore liquidation of the supporting cluster.  
> Even if MTF is still intact, loss of the supporting OI cluster is an early warning that sponsorship is fading.

---

## 7. Side-Aware Display Rules (Fixes the COLPAL-type bug)

| Field | Bullish Trade | Bearish Trade |
|-------|---------------|---------------|
| Recommended Strike | CE (near ATM or supporting zone) | PE (near ATM or supporting zone) |
| Entry Zone | Near Put cluster / demand | Near Call cluster / supply |
| Target | Next Call cluster above | Next Put cluster below |
| Stop / Invalidation | Below supporting Put cluster + structure | Above supporting Call cluster + structure |
| Levels shown as Resistance | Call clusters | Call clusters |
| Levels shown as Support | Put clusters | Put clusters |

**Critical:** Target must always be in the direction of the trade.  
A bearish card must never show a target above entry.

---

## 8. Integration with Existing Systems

### 8.1 With MTF Engine

- MTF decides `allowed_side` (LONG / SHORT / NONE)
- OI Cluster Engine only runs entry/target logic for the allowed side
- If MTF says NONE → no entry/target is generated

### 8.2 With Option Flow Radar

- Radar tells us the quality of the fuel (Fresh Buying, Writing, Unusual, etc.)
- Cluster Engine uses the actual location of that fuel
- High Unusual Score + strong supporting cluster = higher priority idea

### 8.3 With Process Lock

- Once a trade is CONFIRMED, the supporting cluster at the time of confirmation is remembered
- Later liquidation of that specific cluster becomes a trail/exit signal even if new clusters appear

---

## 9. Data Requirements

For each symbol (current expiry):

- Full option chain with OI, Change in OI, Volume, LTP per strike
- Ability to rank and detect local peaks
- Historical OI of key strikes (to detect liquidation vs stable)
- Spot price and basic structure levels (for secondary confirmation)

Caching:
- Cluster map can be refreshed every 3–5 minutes or on significant OI change
- No need to recompute on every tick

---

## 10. Output Object (per confirmed idea)

```json
{
  "symbol": "COLPAL",
  "side": "BEARISH",
  "entry_zone": {
    "from": 1975,
    "to": 1985,
    "reason": "Rejection from Call cluster 1980–2000"
  },
  "supporting_cluster": {
    "strike": 2000,
    "type": "CE",
    "oi": 185000,
    "state": "STABLE"
  },
  "primary_target": {
    "level": 1920,
    "reason": "Next Put cluster 1920"
  },
  "secondary_target": 1880,
  "stop_reference": 2010,
  "exit_warnings": [],
  "cluster_health": "HEALTHY"
}
```

When supporting cluster starts liquidating:

```json
"cluster_health": "WEAKENING",
"exit_warnings": ["Supporting Call cluster 2000 OI declining"]
```

---

## 11. Implementation Order

1. Cluster detection function (peak finding + ranking on Call and Put side)
2. Side-aware supporting / opposing cluster selection
3. Entry zone + Primary target generation
4. Liquidation detection (OI change tracking on key clusters)
5. Wire into existing Process / Momentum cards
6. Fix UI so Target and recommended strike are always side-aware

---

## 12. Acceptance Criteria

After this engine is live:

1. Bearish cards never show targets above entry.
2. Bullish cards never show targets below entry.
3. Recommended strike family matches the side (CE for long, PE for short).
4. Entry zone is preferentially near a supporting OI cluster.
5. Primary target is the next opposing OI cluster.
6. When a supporting cluster liquidates, the card shows a clear warning or auto-tightens.
7. Technical levels are used only as secondary context, not as the main entry/target source.

---

## 13. One-line Summary

> MTF decides the direction.  
> Option Flow decides if the fuel is real.  
> OI Clusters decide exactly where to enter, where to take profit, and when the fuel is dying.

---

**End of Specification**
