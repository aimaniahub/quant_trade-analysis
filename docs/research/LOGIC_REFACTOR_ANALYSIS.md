# LOGIC REFACTOR ANALYSIS — FlowRadar & Option Chain
## Full System Audit → Problem Diagnosis → Strategy Blueprint

**Date:** September 2, 2026  
**Author:** Deep system pass on quant_trade-analysis repo  
**Status:** Full diagnosis + implementation roadmap

---

> [!CAUTION]
> **Core Problem (one line):** The system is labelling the *presence of a chain* (every F&O stock has OI, volume, walls) instead of labelling a *rare, quantified anomaly relative to that name's own book*. If every stock gets every tag, no filter can isolate a real move. The result in live market: filters are useless, trades are random, momentum is missed before it explodes.

---

## 1. Full Architecture Map (What Actually Exists)

### Backend Services

```
backend/app/services/
├── option_flow_radar.py      (2332 lines) — Main scan orchestrator
├── chain_anomaly.py          (1897 lines) — Primary decision engine (evaluate → grade)
├── radar_signal_engine.py    (738 lines)  — CE/PE classification, LIS, Greek quality
├── signal_interpreter.py     (286 lines)  — PCR/IV/buildup narrators
├── option_analytics.py       (1125 lines) — Max pain, PCR, walls, IV, straddle, buildups
├── desk_decision.py          (662 lines)  — HTF → PCR → buildup decision pipeline
├── fno_intelligence.py       (1001 lines) — Time-window aware analysis engine
├── confluence.py             (18435 bytes)— Multi-signal confluence
├── levels.py                 (39450 bytes)— Futures buildup, S/R levels
├── idea_book.py              (35679 bytes)— Trade idea management
├── ai_ranker.py              (10776 bytes)— AI/news fusion ranking
└── mtf_engine.py             (19022 bytes)— Multi-timeframe engine
```

### Frontend Components

```
frontend/components/
├── OptionFlowRadar.tsx   (1161 lines, 52KB) — Main FlowRadar board UI
├── StockAnalysis.tsx     (1576 lines, 72KB) — Stock detail analysis
├── NiftySentimentCards.tsx — Index cards
├── HighVolumeScanner.tsx — Volume anomaly scanner
├── MA7200Scanner.tsx     — MA crossover scanner
└── RSIDivergenceScanner.tsx — RSI scanner
```

---

## 2. Current System Logic Flow

```
Fyers API → option_flow_radar.py harvest()
         → chain_anomaly.analyze_chain()
              ├── structure_layer() → PCR, walls, gamma, IV, buildup, straddle
              ├── futures_layer()   → futures state, basis, fade check
              ├── session_metrics() → VWAP, EMA20, ATR from 15m bars
              ├── strike_anomalies() → SIZE / HIGH_STRIKE_VOL flags per strike
              ├── wall_activity()   → WALL_SUPPORT / WALL_RESISTANCE at put/call wall
              ├── wall_and_straddle_flags() → WALL_SHIFT, STRADDLE_CRUSH/EXPAND
              ├── chain_volume_regime() → vs past days average
              ├── flow_bias_from_anomalies() → BULLISH / BEARISH / CONFLICT
              ├── decide_grade()    → TRADEABLE / WATCH / QUIET
              └── build_trade_card() → entry, stop, target, R:R
         → summarize_report()
         → _repartition_hits() → flagged, watch, alert_box
         → _publish_live_board()
         → Frontend OptionFlowRadar.tsx renders board
```

---

## 3. FAILURE MODE ANALYSIS (Why It's Junk in Live Market)

### 3.1 Tag Inflation — The #1 Problem

**What the code does:**
```python
# frontend flagsOf() in OptionFlowRadar.tsx
high_oi    = oi_added >= 15000          # Almost every liquid stock qualifies
high_vol   = opt_volume >= 150000       # NIFTY, BANKNIFTY qualify instantly
support    = top_anomaly.type == 'WALL_SUPPORT'   # put wall exists on ALL chains
resistance = top_anomaly.type == 'WALL_RESISTANCE' # call wall exists on ALL chains
vol_spike  = vol_x >= 2.0 or highVol   # vol_x=2 is a LOW bar for active names
early_mover= score >= 60 and (volX >= 1.8 or highVol or highOi)
```

**What this means:**
- NIFTY50 vol > 30L contracts → always `high_vol`
- Every F&O stock has a put wall → always `support` possible
- Every F&O stock has a call wall → always `resistance` possible
- vol_x >= 2x is too easy for actively traded names
- Result: 130+ stocks get `OI VOL SUP RES` simultaneously

**The bar is wrong. Tags must be EXCLUSIVE, not inclusive.**

---

### 3.2 Momentum Scoring Doesn't Capture Real Momentum

**Current LIS (Layered Intent Score):**
```python
def compute_lis_v2(...):
    oi_score      = min(abs(oi_change_pct) / 20.0, 1.0) * 30.0   # 30 pts
    vol_score     = min(vol_excess / 4.0, 1.0) * 25.0              # 25 pts
    momentum_score= compute_momentum_score(...)                      # 15 pts
    vwap_score    = (1.0 - min(abs(vwap_dev_pct) / 2.0, 1.0)) * 15.0  # 15 pts
    trigger       = 10.0 if above_ema20 else 0.0                    # 10 pts
    delivery_score= min(delivery_ratio / 2.0, 1.0) * 5.0           # 5 pts
```

**Problems:**
1. `oi_score` rewards ANY OI change including Long Unwinding (exit, not entry)
2. `vwap_score` REWARDS stocks near VWAP = sideways, not momentum
3. `trigger = 10 if above_ema20` — binary, flat, no acceleration check
4. ZERO weight given to: velocity (rate of OI change), cluster concentration, chain-wide acceleration
5. VOR (Vol/OI ratio) not used at all — this is what US flow desks filter on first

---

### 3.3 The Wall Logic Is Structurally Broken

**Current wall detection:**
```python
put_wall = structure.get("put_wall")  # argmax PE OI below spot — ALWAYS EXISTS
near_put = abs(strike - put_wall) <= step * WALL_STEPS
# Then check: vol >= vol_floor*2 and abs(oi_pct) >= WALL_OI_PCT
```

**Problems:**
1. `put_wall = argmax(PE OI below spot)` — this is true for EVERY stock. Every F&O stock has a put wall. This is a chain property, not an event.
2. No velocity check: is the OI at this wall GROWING since last harvest? Static OI at a wall is noise. Growing OI at a wall = institutional write/buy happening NOW.
3. Wall SHIFT detection exists but is weakly weighted (0.75 pts) — a migrating wall is one of the strongest signals in the market.

---

### 3.4 Grade Decision Logic Has Too Many Escape Hatches

**From `decide_grade()`:**
```python
# These all downgrade TRADEABLE → WATCH:
1. fut_missing and not has_strong and not vol_expanded → WATCH
2. exhaustion_only → WATCH
3. fade (futures SHORT_COVERING or LONG_UNWINDING) → WATCH  ← KILLS SQUEEZES
4. aligned < 2 (fewer than 2/3 layers agree) → WATCH
5. not has_any (no anomaly at all) → WATCH
6. HTF gate blocks → WATCH
7. index_ctx divergent → WATCH
8. not persisted (needs same bias on previous harvest) → WATCH (even with TRADEABLE intent)
```

**In live fast market:**
- Futures data often missing intraday → escape hatch #1 fires
- SHORT_COVERING in futures appears at squeeze START → escape hatch #3 kills the squeeze signal
- Persistence requirement: needs 2 harvests (each harvest = 4+ min scan cycle) = you miss the first 8 minutes of the move
- **Result: Legitimate early-momentum setups get systematically downgraded to WATCH**

---

### 3.5 Short Squeeze Signal Is Actively Blocked

**The worst design bug in the system:**
```python
FADE_FUTURES = {"SHORT_COVERING", "LONG_UNWINDING"}
# chain_anomaly.decide_grade():
fade = bool(futures.get("fade"))
if fade:
    why.append(f"Futures {futures.get('state')} is fade-risk — cap WATCH")
    return GRADE_WATCH, chain_bias, GRADE_WATCH, why
```

**What happens in a real short squeeze:**
1. Futures show SHORT_COVERING (shorts being forced out)
2. Simultaneously: aggressive CE buying at ATM (new longs entering)
3. PCR dropping fast (puts being abandoned)
4. Stock is about to explode upward

**The system sees `SHORT_COVERING` → sets `fade=True` → caps at WATCH → MISSES THE SQUEEZE.**

This is a fundamental logic error. Short covering in futures is a fade only if options are ALSO unwinding. If futures are covering AND options are buying, it's a SQUEEZE — the highest-urgency trade in F&O.

---

### 3.6 Signal Classification Threshold Problems

**From `radar_signal_engine.classify_signal()`:**
```python
oi_up = oi_change_pct >= 8.0   # threshold
pr_up = option_price_change_pct >= 1.5   # threshold
```

**The thresholds kill small-cap momentum:**
- `oi_up = 8%` in a 2000-OI contract = 160 contracts changed. That's noise.
- `pr_up = 1.5%` on an OTM option with LTP of ₹5 = ₹0.075 change. That's a tick.
- No filter on ABSOLUTE OI added — percentage-only thinking misses "₹100 crore of new premium" signal

**What the real institutional signal looks like:**
- Put Writing = OI ↑ + Premium ↓ + STRIKE NEAR ATM + OI added > 50k contracts + volume > 2x chain median
- Not just "OI went up 8%"

---

### 3.7 Frontend Compounds Every Backend Problem

**OptionFlowRadar.tsx display issues:**

1. **Board sorts by setup_score** — setup_score doesn't include acceleration. A stock with steady-low-vol can outscore a stock that just erupted.

2. **Filter tabs use OR logic** — 100+ stocks show under "Call Buying" because any stock with `call buying` in top_anomaly_label qualifies. OR-filter on boolean flags = no discrimination.

3. **Chain table = wall of Neutral/Inconclusive** — every strike shown equal weight. Anomalous strikes buried. The anomaly should be the HERO, rest dimmed.

4. **No urgency/freshness signal** — `cache_age_seconds` exists in data but not prominently displayed. Trader has no idea if the signal is 30 seconds or 20 minutes old. Stale trade cards = blowups.

5. **No velocity display** — Is OI being added at an increasing rate? Is VOR high? This information isn't shown anywhere in the UI.

---

## 4. What Real Exploding Momentum Looks Like (We're Missing)

### Type 1: Institutional Footprint ("Smart Money Early")
```
Window: 10:30–11:30 AM
Signals:
  - Specific strike: OI added > 5x chain-median-per-strike
  - Same side (all CE or all PE), premium EXPANDING (buyers, not writers)
  - Vol/OI ratio (VOR) > 0.8 (huge turnover = urgency)
  - Within 2% of ATM
  - Futures long buildup simultaneously
  - 15m bars: above VWAP, volume > yesterday's same bar
Result: Stock accelerates in direction within 15-45 minutes. Option premium 2-3x.
Why missed: Persistence blocks first-harvest TRADEABLE. VOR not computed.
```

### Type 2: Wall Absorption Break ("Wall Flip")
```
Setup:
  - Call wall at 2400 for past 3 days
  - Today: massive CE buying at 2400 (OI up + premium up)
  - CE vol at 2400 > 3x yesterday's same-strike vol
  - Spot reaches 2400, bounces, then pushes through with volume
Result: Dealer gamma squeeze → stock gaps to next resistance in 5-15 min
Why missed: WALL_RESISTANCE flags the wall as bearish (resistance). No
  "being consumed" signal. No detection of "existing writers covering while
  new buyers attack the wall simultaneously".
```

### Type 3: Short Squeeze ("Trapped Short")
```
Setup:
  - Futures SHORT_BUILDUP for 2-3 days
  - Today: futures OI dropping while price goes up = SHORT_COVERING
  - CE buying spikes simultaneously (shorts covering via options)
  - PCR dropping sharply
Result: Trapped shorts forced to buy → 3-5% stock move in 30 minutes
Why missed: FADE_FUTURES blocks SHORT_COVERING. System literally prevents
  this signal from reaching TRADEABLE grade. This is the worst bug.
```

### Type 4: Straddle Explosion ("IV Burst")
```
Setup:
  - IV flat all morning (straddle flat or compressing)
  - Suddenly: OTM call IV spikes 3-5 points in 15 minutes
  - ATM straddle premium jumps > 8%
  - PCR drops sharply
  - VOR on ATM CE > 0.5 and rising
Result: Breakout of compression, directional move starts, options explode
Why missed: STRADDLE_EXPAND compares to previous harvest only (single datapoint).
  No straddle history in session. No compression → explosion detection. No
  IV acceleration (rate of change, not level) tracking.
```

---

## 5. Strategy Blueprint: What to Build

### 5.1 Vol/OI Ratio (VOR) — The Primary Momentum Signal

**Not implemented anywhere. Add to `radar_signal_engine.py`:**

```python
def compute_vor(volume: float, oi: float) -> float:
    """
    Volume-to-OI ratio. High = fresh positions being opened aggressively.
    VOR > 0.8 = more volume than standing OI = massive turnover = URGENCY
    VOR > 0.5 = active accumulation in progress
    VOR < 0.2 = slow drip, mostly old positions, no fresh entry
    """
    if oi <= 0:
        return 0.0
    return min(volume / oi, 5.0)  # cap at 5 to avoid divide-by-tiny-OI distortion
```

This single number is what US flow desks filter on first. VOR > 1.0 means volume EXCEEDED standing OI — that's an extremely rare and powerful signal.

---

### 5.2 OI Velocity Tracking (Missing Entirely)

**Add harvest timestamps to `build_digest()` in `chain_anomaly.py`:**

```python
# In build_digest():
return {
    ...existing fields...,
    "harvest_ts": now.isoformat(),   # ADD THIS
    "legs": legs,
}

# New function:
def compute_oi_velocity(
    current_oi: float,
    prev_harvest_oi: float,    # from prev_digest.legs[strike:side]["oi"]
    harvest_interval_sec: float,
) -> float:
    """OI contracts being added per minute. The rate, not just the level."""
    if harvest_interval_sec <= 0 or prev_harvest_oi <= 0:
        return 0.0
    oi_delta = current_oi - prev_harvest_oi
    return oi_delta / (harvest_interval_sec / 60.0)

def is_accelerating(velocity_now: float, velocity_prev: float) -> bool:
    """Is the institutional entry speeding up?"""
    if velocity_prev <= 0:
        return velocity_now > 500  # floor: at least 500 contracts/min
    return velocity_now > velocity_prev * 1.5
```

---

### 5.3 Fix the Persistence Trap

**Current (always blocks first-harvest TRADEABLE):**
```python
if not persisted:
    return GRADE_WATCH, chain_bias, GRADE_TRADEABLE, ["Needs one more harvest..."]
```

**New (persistence only for soft signals):**
```python
# Persistence NOT required when any of:
# 1. WALL_SUPPORT or WALL_RESISTANCE anomaly (wall signals are immediate)
# 2. vol_regime.expanded (chain vol > 1.35x average = something happening NOW)
# 3. FOOTSTEP_EARLY (OI velocity + VOR + acceleration)
# 4. SQUEEZE_ACTIVE (futures covering + CE buying)

bypass_persistence = (
    has_strong          # wall/cluster anomaly
    or vol.get("expanded")
    or footstep_early_flag
    or squeeze_active_flag
)

if not bypass_persistence and not persisted:
    return GRADE_WATCH, chain_bias, GRADE_TRADEABLE, ["Needs one more harvest..."]
# else: proceed to TRADEABLE
```

---

### 5.4 Fix Short Squeeze Being Blocked

**Remove squeeze from fade list in `chain_anomaly.py`:**

```python
# Current (WRONG):
FADE_FUTURES = {"SHORT_COVERING", "LONG_UNWINDING"}

# New (detect squeeze first, then decide):
def detect_squeeze_active(
    futures: Dict,
    flow_bias: str,
    anomalies: List[Dict],
    chain: List[Dict],
    spot: float,
) -> bool:
    """
    Short squeeze: futures covering + option buyers entering simultaneously.
    This is NOT a fade — it's the highest-urgency bullish setup.
    """
    fut_state = str(futures.get("state") or "").upper()
    if fut_state != "SHORT_COVERING":
        return False
    if flow_bias != "BULLISH":
        return False
    # CE buying must be fresh (not just exhaustion)
    ce_buying = any(
        a.get("label") == "Fresh Call Buying" and not a.get("exhaustion")
        for a in anomalies
    )
    return ce_buying

# In decide_grade():
squeeze_active = detect_squeeze_active(futures, flow_bias, anomalies, chain, spot)
if squeeze_active:
    fade = False   # Override fade flag for squeezes
    grade_boost = True  # Can reach TRADEABLE on first harvest
```

---

### 5.5 New "Footstep Score" (Velocity-Weighted)

**Replace LIS as primary ranking score:**

```python
def compute_footstep_score(
    vor: float,                    # Vol/OI ratio at strike
    oi_velocity: float,            # OI contracts/min being added
    is_accelerating: bool,         # Velocity increasing vs last harvest
    chain_vol_expansion: float,    # Chain vol vs past-day average ratio
    premium_direction_match: bool, # CE buying → premium rising? (not writing)
    atm_dist_pct: float,           # Distance from ATM
    cluster_count: int,            # Adjacent same-direction strikes
    straddle_state: str,           # "COMPRESSED"/"EXPLODING"/"NORMAL"
) -> float:
    """Score 0-100. Rewards early entry velocity signals."""
    score = 0.0

    # 1. VOR — the urgency signal (30 pts)
    if vor >= 0.8:   score += 30
    elif vor >= 0.5: score += 20
    elif vor >= 0.3: score += 10

    # 2. OI velocity — institutions actively entering (25 pts)
    if oi_velocity > 5000:    score += 25
    elif oi_velocity > 2000:  score += 15
    elif oi_velocity > 500:   score += 8

    # 3. Acceleration — footstep getting louder (15 pts)
    if is_accelerating: score += 15

    # 4. Premium direction match — real buying, not writing (15 pts)
    if premium_direction_match: score += 15

    # 5. ATM proximity — near-ATM matters most (10 pts)
    if atm_dist_pct <= 1.0:      score += 10
    elif atm_dist_pct <= 2.5:    score += 6
    elif atm_dist_pct <= 4.0:    score += 2

    # 6. Cluster bonus — concentration = intention (5 pts)
    if cluster_count >= 4: score += 5
    elif cluster_count >= 2: score += 2

    # Straddle state multiplier
    if straddle_state == "EXPLODING":
        score = min(score * 1.25, 100)
    elif straddle_state == "COMPRESSED":
        score = min(score * 1.10, 100)

    return round(min(score, 100), 1)
```

---

### 5.6 Tag Exclusivity Enforcement

**New rule — a stock gets ONE primary tag + optional location + optional size:**

```python
# Tier 1: RARE (< 5% of universe) — highest priority, exclusive
FOOTSTEP_EARLY    # VOR > 0.5 + OI velocity + acceleration + ATM near
SQUEEZE_ACTIVE    # Futures SHORT_COVER + CE buying + PCR falling
WALL_BREAK        # Price crossed call wall + 3x CE vol at wall
SMART_WRITE       # OI added > 2x floor at ATM + premium falling (writer intent)
OTM_CLUSTER       # 4+ adjacent OTM strikes same side, OI added > floor each

# Tier 2: UNCOMMON (< 15% of universe)
WALL_SUPPORT_LIVE   # Put wall + OI being ADDED now (not just static)
WALL_RESIST_LIVE    # Call wall + OI being added now
VOL_SHOCK           # Chain vol > 2x 5-day average (raise from current 1.35x)
STRADDLE_BURST      # Straddle > 8% in < 30 min
SKEW_DETONATION     # IV skew shift > 3 points since session open

# Rule: ONE Tier 1 + ONE Tier 2 max per stock, no more stacking
```

---

### 5.7 Straddle Compression → Explosion Detector

**Add straddle_history to digest:**

```python
# In build_digest():
straddle_history = list((prev_digest or {}).get("straddle_history") or [])
cur_straddle = _f((structure.get("straddle") or {}).get("straddle"))
if cur_straddle > 0:
    straddle_history.append({"value": cur_straddle, "ts": now.isoformat()})
straddle_history = straddle_history[-10:]  # keep last 10 harvests

# New detector:
def straddle_compression_state(straddle_history: List[Dict], current: float) -> str:
    if len(straddle_history) < 3:
        return "UNKNOWN"
    early_avg = sum(h["value"] for h in straddle_history[:3]) / 3
    if current < early_avg * 0.85:
        return "COMPRESSED"   # coiled spring — watch for direction break
    if current > early_avg * 1.12 and current > straddle_history[-2]["value"]:
        return "EXPLODING"    # detonating — get in direction now
    return "NORMAL"
```

---

### 5.8 PCR Velocity Signal

**Add PCR history to digest, compute velocity:**

```python
# In build_digest():
pcr_history = list((prev_digest or {}).get("pcr_history") or [])
pcr_history.append({"oi_pcr": structure.get("oi_pcr"), "ts": now.isoformat()})
pcr_history = pcr_history[-10:]

# PCR velocity:
def pcr_velocity_signal(pcr_history: List[Dict]) -> Dict:
    if len(pcr_history) < 2:
        return {"signal": "NO_HISTORY", "bias": "NEUTRAL"}
    current = pcr_history[-1]["oi_pcr"] or 1.0
    prev = pcr_history[-2]["oi_pcr"] or 1.0
    delta = current - prev
    if delta < -0.15:   # PCR dropped fast
        return {"signal": "PCR_COLLAPSING", "bias": "BEARISH"}
    if delta > 0.15:    # PCR jumped fast
        return {"signal": "PCR_SURGING", "bias": "BULLISH"}
    return {"signal": "STABLE", "bias": "NEUTRAL"}
```

---

## 6. The 5 Tradeable Setups (Full Spec)

### Setup 1: WALL_ABSORPTION_BREAK
```
Grade: A+ (best R:R, most rare)
Trigger: CE OI at call_wall: RISING + premium RISING simultaneously
         + spot within 0.5% of call_wall
         + CE vol at wall > 3x yesterday vol at same strike
         + Futures: NOT SHORT_COVERING (must be NEUTRAL or LONG_BUILDUP)
Entry:   On close of 15m candle above call_wall
Stop:    Put wall level (structural invalidation)
Target:  Next call wall or 1.5x ATR above entry
Window:  10:30 AM – 2:00 PM (avoid last 1 hour)
```

### Setup 2: INSTITUTIONAL_FOOTSTEP
```
Grade: A (early entry, highest accuracy with right filters)
Trigger: VOR > 0.6 on ATM ± 1% strike
         + OI velocity accelerating (this harvest > 1.5x last harvest same strike)
         + Cluster: ≥3 adjacent strikes same side showing same signal
         + Straddle NOT expanding (options still cheap for buyer)
         + Futures: LONG or NEUTRAL (not covering)
Entry:   At open of next 15m candle after trigger
Stop:    0.5% below entry (CE) or above (PE)
Target:  Next resistance/support OR max_pain as magnet
Window:  10:30 AM – 1:00 PM
```

### Setup 3: PCR_VELOCITY_BULL/BEAR
```
Grade: B (momentum confirmation)
Trigger: PCR drops > 0.15 in one harvest (BULL) or rises > 0.15 (BEAR)
         + Futures: LONG_BUILDUP (not SHORT_COVERING)
         + Spot: Above VWAP (BULL) or Below VWAP (BEAR)
Entry:   Buy CE ATM (BULL) or PE ATM (BEAR)
Stop:    Put wall (BULL) or Call wall (BEAR)
Target:  Call wall (BULL) or Put wall (BEAR)
Window:  Any time 10:30 AM – 2:30 PM
```

### Setup 4: SQUEEZE_ACTIVE (High urgency)
```
Grade: A+ (fastest moving, hardest to time)
Trigger: Futures: SHORT_COVERING
         + CE OI at ATM: RISING + CE premium RISING (fresh buying, NOT covering)
         + PCR: dropping rapidly (>0.10 per harvest)
         + VOR on CE side > 0.7
Entry:   Market buy CE (urgency mode — stale quotes = loss)
Stop:    When VOR drops below 0.3 (buyers exiting) OR spot drops below VWAP
Target:  Next 1-2 strikes OTM from entry CE
Window:  Can happen any time; highest frequency: 11:00 AM – 1:00 PM
Note:    Fastest decaying setup — must act within minutes of signal
```

### Setup 5: STRADDLE_COIL_BREAK
```
Grade: B (volatility expansion play, works in any direction)
Trigger: Straddle compressed < 85% of session-open value (COMPRESSED state)
         + Spot within ±0.3% of max_pain (gamma wall pinning)
         + VIX above 14
         + Suddenly: CE OR PE volume > 2x chain median on that side (direction declared)
Entry:   Buy the side that is spiking (CE or PE)
Stop:    If straddle drops back below compression ratio
Target:  100% straddle return (premium returns to session-open level)
Window:  Often fires: 11:00 AM – 12:30 PM (compression builds in morning, breaks midday)
```

---

## 7. Priority Implementation Order

### Phase 1 (Fix Biggest Failures — Do These First):

| Priority | Change | File | Impact |
|---|---|---|---|
| 1 | Fix SHORT_COVERING false fade → add `detect_squeeze_active()` | `chain_anomaly.py` | Unblocks squeeze signal |
| 2 | Remove persistence requirement for WALL + VOL_EXPAND signals | `chain_anomaly.decide_grade()` | Catches first-candle momentum |
| 3 | Add VOR computation to strike_anomalies | `chain_anomaly.py`, `radar_signal_engine.py` | Primary momentum filter |
| 4 | Raise tag floors: high_vol ≥ 200k, oi_added ≥ 50k for SIZE | `OptionFlowRadar.tsx:flagsOf()` | Reduce tag inflation |
| 5 | Add `cache_age_seconds` as prominent urgency indicator in UI | `OptionFlowRadar.tsx` | Prevent stale-signal trades |

### Phase 2 (Add Velocity Signals):

| Priority | Change | File | Impact |
|---|---|---|---|
| 6 | Add `harvest_ts` to `build_digest()` | `chain_anomaly.py` | Enables velocity computation |
| 7 | Add OI velocity computation per strike | `chain_anomaly.py` | Institutional entry detection |
| 8 | Add `footstep_score` replacing LIS as primary score | `radar_signal_engine.py` | Velocity-first ranking |
| 9 | Add `FOOTSTEP_EARLY` tag (bypasses persistence) | `chain_anomaly.py` | Early signal surfacing |
| 10 | Add `straddle_history` to digest | `chain_anomaly.build_digest()` | Compression/explosion detection |
| 11 | Add `pcr_history` to digest | `chain_anomaly.build_digest()` | PCR velocity signal |

### Phase 3 (Full Overhaul):

| Priority | Change | File | Impact |
|---|---|---|---|
| 12 | Tag exclusivity enforcement (1 primary + 1 location + 1 size) | `chain_anomaly.py`, `option_flow_radar.py` | Signal quality |
| 13 | Straddle COMPRESSED / EXPLODING detector | `chain_anomaly.py` | New setup 5 |
| 14 | PCR velocity signal → `PCR_SURGING`/`PCR_COLLAPSING` tags | `chain_anomaly.py` | Setup 3 |
| 15 | UI: sort by footstep_score, dim Neutral chain rows, show VOR | `OptionFlowRadar.tsx`, `OptionChainTable.tsx` | Usable UI |

---

## 8. What NOT to Change (Working Correctly)

1. **classify_signal() CE/PE matrix labels** — correct, just threshold tuning needed
2. **Wall identification** (argmax PE/CE OI) — correct definition
3. **Max pain computation** — correct formula, meaningful as magnet level
4. **ATM straddle computation** — correct
5. **Greek quality score (0–20)** — reasonable delta sweet-spot filter
6. **Index context gate** — correct (stock can't rally against crashing NIFTY)
7. **Fyers API integration** — works, quota management reasonable
8. **Redis persistence** — scan board persistence across restarts is good
9. **chain_volume_regime()** — correct approach, just raise the vol_expand threshold to 2.0x from 1.35x

---

## 9. Root Cause Summary Table

| Problem | Root Cause | File | Fix |
|---|---|---|---|
| Every stock gets every tag | Thresholds too low; flags are attributes not events | `radar_signal_engine.py`, `OptionFlowRadar.tsx` | Raise floors, enforce exclusivity |
| Momentum missed on first appearance | 2-harvest persistence required for TRADEABLE | `chain_anomaly.decide_grade()` | Remove persistence for WALL/VOL_EXPAND/FOOTSTEP |
| Short squeeze blocked | `FADE_FUTURES` includes SHORT_COVERING | `chain_anomaly.decide_grade()` | Add squeeze detection, bypass fade when CE buying simultaneous |
| OI velocity not tracked | No timestamps in digest, no velocity math | `chain_anomaly.build_digest()` | Add harvest_ts, compute velocity per strike |
| VOR (Vol/OI) not used | Not implemented anywhere in codebase | `radar_signal_engine.py` | Add VOR as primary momentum filter |
| Stale signals in trade cards | cache_age not prominently shown | `OptionFlowRadar.tsx` | Urgency freshness indicator |
| Chain table unusable | All rows equal weight; Neutral rows fill screen | `OptionChainTable.tsx` | Dim Neutral rows, pin anomaly rows to top |
| LIS rewards sideways | vwap_score rewards near-VWAP = not momentum | `radar_signal_engine.py` | Replace vwap_score with velocity/acceleration score |
| Trade cards too conservative | Too many escape hatches; no in-motion card | `chain_anomaly.build_trade_card()` | Add in-motion card for FOOTSTEP_EARLY |
| PCR is static level | No PCR velocity/rate tracking | `chain_anomaly.build_digest()` | Add pcr_history, compute PCR rate of change |
| Wall detection not live | Static wall existence vs dynamic OI growth at wall | `chain_anomaly.wall_activity()` | Require OI growth since prev_digest, not just OI level |
| Straddle has single snapshot | No session history for compression detection | `chain_anomaly.build_digest()` | Add straddle_history list (last 10 harvests) |

---

## 10. The Single Organizing Principle

> **Everything built so far answers: "WHAT IS THE STRUCTURE?"**
> **What is completely missing: "WHO IS ACTING RIGHT NOW AND HOW FAST?"**

The structure tells you WHERE the game will be played.
The velocity tells you WHEN the move is starting.

**Current system: 100% structure. 0% velocity.**

Real momentum trades require:
- **Structure** (PCR, walls, buildup — WHICH direction is likely)
- **Velocity** (OI rate, VOR, acceleration — IS IT STARTING NOW)
- **Exclusivity** (rare tags, not tag soup — IS THIS SIGNAL REAL)

**The footstep is the velocity. Catch it before the crowd confirms.**

---

## 11. Files to Read for Implementation Context

| File | Why |
|---|---|
| [`chain_anomaly.py`](file:///d:/quant_trade-analysis/backend/app/services/chain_anomaly.py) | Add velocity, fix persistence, fix squeeze |
| [`radar_signal_engine.py`](file:///d:/quant_trade-analysis/backend/app/services/radar_signal_engine.py) | Add VOR, add footstep_score, fix LIS |
| [`option_flow_radar.py`](file:///d:/quant_trade-analysis/backend/app/services/option_flow_radar.py) | Add tag exclusivity enforcement in `_repartition_hits()` |
| [`OptionFlowRadar.tsx`](file:///d:/quant_trade-analysis/frontend/components/OptionFlowRadar.tsx) | Fix `flagsOf()` thresholds, add urgency display, sort by footstep_score |
| [`quantopt.md`](file:///d:/quant_trade-analysis/quantopt.md) | Supporting research on US flow desks, GEX, Indian F&O practice |
| [`flow fix.md`](file:///d:/quant_trade-analysis/flow%20fix.md) | Earlier diagnosis of signal classification issues |

---

*End of Logic Refactor Analysis v1.0*
