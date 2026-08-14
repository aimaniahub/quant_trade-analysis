# 7 / 200 Cross — Advanced Realtime Momentum Design

**Status:** Design only (do not implement until approved)  
**Strategy name:** 15m 7/200 EMA First-Cross Momentum + Option Chain Confirmation  
**Related code (current v1):** `ma7200_scanner.py`, `/strategies/ma7200/*`, `MA7200Scanner.tsx`  
**Date:** 2026-08-12

---

## 1. Purpose

Upgrade the working **direct-API 7/200 scanner** from:

- “find any recent 7/200 cross with volume”

to:

- **realtime / near-realtime capture of true momentum first crosses**
- ignore **stale** crosses
- ignore **sideways chop / rebound re-crosses** that flood the list

The MA cross still **only creates candidates**.  
**Option chain confirmation** remains the final decision maker (same two-step philosophy as v1).

---

## 2. Problems with v1 (what we learned)

| Issue | Effect |
|--------|--------|
| Accepting crosses within last ~10–12 bars | List includes crosses that already ran; late entry |
| No “first cross in N days” rule | Sideways markets: 7 wiggles above/below 200 many times → noise |
| Full history scan is batch REST | Fine for discovery; not tick-aware for “just happened” |
| Volume filter alone | Reduces noise but not multi-day re-cross spam |

**User intent (this design):**

1. Only stocks whose cross is **about 2 candles old** (fresh).  
2. That cross must be the **first 7/200 cross in the last 15 days** (up *or* down).  
3. That combination = **momentum stocks**, not rebound chop.

---

## 3. Core definitions

### 3.1 Moving averages (locked)

| Item | Value |
|------|--------|
| Timeframe | **15-minute** |
| Fast MA | **7-period EMA** |
| Slow MA | **200-period EMA** |
| Consistency | EMA only (not SMA) for both |

### 3.2 Fresh cross window (replace “lookback 10–12”)

**Target:** cross completed on the bar that is **exactly 1 or 2 closed 15m candles ago**.

| Bars ago | Meaning | Action |
|----------|---------|--------|
| 0 (forming) | Current incomplete 15m bar | Optional: **pre-alert / nearing** only — not a final candidate |
| **1** | Last fully closed candle was the cross bar | **Primary candidate** |
| **2** | Cross on the candle before last close | **Still fresh** (allowed) |
| ≥ 3 | Older | **Reject** for live list |

Rationale: “just crossed 2 candles away” = still early, not already 5–10 bars into the move.

### 3.3 First-cross-in-15-days rule (anti-sideways)

Look back **15 calendar days** of 15m history (or ~15 trading days if you prefer bar-count — see §8).

Within that window, count how many **valid directional 7/200 crosses** occurred (bullish or bearish).

**Accept only if:**

```
number_of_valid_crosses_in_15d_window == 1
AND that single cross is the fresh one (bars_ago ∈ {1, 2})
```

Interpretation:

- **First break of the 200 structure in two weeks** → genuine regime/momentum attempt.  
- Multiple flips 7 above/below 200 in 15 days → **chop / rebound** → drop even if latest cross is “fresh”.

Optional soft mode (later): allow 2 crosses if second is same direction and first was opposite “failed” with volume fail — **not in v2 strict mode**.

### 3.4 Cross geometry (same as v1, keep)

**Bullish candidate**

- Previous bar: `EMA7 ≤ EMA200`  
- Cross bar: `EMA7 > EMA200`  
- Cross bar close **above both** EMAs  

**Bearish candidate**

- Previous bar: `EMA7 ≥ EMA200`  
- Cross bar: `EMA7 < EMA200`  
- Cross bar close **below both** EMAs  

### 3.5 Volume filter (keep, slightly tighten for freshness)

On the **cross candle** (or max of cross candle vs last-3 avg):

```
volume_ratio = cross_vol / avg(volume of 10 candles immediately before cross)
require volume_ratio ≥ 1.5
```

Prefer **rising volume** on last 2–3 bars into the cross (soft score, not hard kill unless ratio fails).

### 3.6 Session filters (keep)

- Prefer skip first 15m and last 15m of cash session for **final** candidate.  
- Forming-bar alerts can still fire near open if needed later.

---

## 4. “No use of already crossed line” — precise meaning

### Reject

| Case | Why |
|------|-----|
| Cross 3+ closed bars ago | Already in play; late |
| Cross today but **not first** in 15 days | Rebound / range oscillation |
| Price re-tested 200 many times with 7 flipping | Sideways |
| Cross with weak volume | Fake break |

### Accept

| Case | Why |
|------|-----|
| bars_ago = 1 or 2 | Fresh |
| Only valid 7/200 cross in last 15 days | First momentum break |
| Volume ≥ 1.5× prior 10 | Participation |
| Close on correct side of both MAs | Confirmed close |

**Do not list** stocks that are “still above/below 200 after an old cross” without a **new** first-cross event.

---

## 5. Realtime / tick-by-tick architecture (target)

### 5.1 Two layers

```
Layer A — LIVE WATCH (tick / 1m aggregation)
  Subscribe watchlist (or full F&O in chunks)
  Maintain rolling 15m candle builder per symbol
  Maintain rolling EMA7 / EMA200 state (incremental if possible)
  On each 15m CLOSE (or tick that finalizes bar):
      evaluate fresh cross + first-in-15d
  On tick while bar forming (optional):
      if EMA7 approaching EMA200 within X% → NEARING alert only

Layer B — CONFIRM (on demand, same as v1)
  User / auto queue: Analyze option chain
  ≥2/5 OC rules → CONFIRMED else AVOID
```

### 5.2 Why not “tick every symbol full 40-day REST every second”

Impossible under Fyers limits. Realtime means:

1. **Bootstrap once** (or daily): pull 15m history for universe (direct API, paced job — already works).  
2. **Seed EMA state + 15d cross history** in memory/Redis.  
3. **Then only process ticks / new closed 15m bars** — no full re-download every scan.

### 5.3 Data flow (implementation sketch)

```
[Fyers WS ticks] optional
       │
       ▼
 CandleAggregator (1m → roll into 15m)
       │
       ▼
 MA7200LiveEngine
   - per symbol: ema7, ema200, last_cross_ts, cross_count_15d
   - on_bar_close_15m(symbol, bar):
         update emas
         if crossed_this_bar and bars_ago logic:
             if is_first_cross_in_15d():
                 emit CANDIDATE
       │
       ▼
 Candidate bus / UI table (fresh only)
       │  [Analyze Chain]
       ▼
 Option confirmation (existing)
```

### 5.4 Bootstrap job (reuse v1 direct API)

Keep current **direct history API job** as:

- **Cold start / daily reseed** of state for all F&O  
- Not the primary “every click” UX once live is up  

Live mode: UI shows **streaming candidates**; “Reseed” button runs full REST rebuild.

---

## 6. First-cross-in-15-days algorithm (detail)

### Inputs

- Array of closed 15m candles covering **≥ 15 calendar days** (prefer ≥ 20 days for 200 EMA seed).  
- Precomputed `ema7[i]`, `ema200[i]` for all bars with defined EMAs.

### Steps

1. Find all indices `i` where a **valid** bull or bear cross occurs (geometry + optional volume on that bar).  
2. Restrict to crosses with timestamp ≥ `now - 15 days`.  
3. Let `C = list of those crosses sorted by time`.  
4. Fresh window: last closed bar index `n-1` and `n-2` (bars_ago 1 and 2).  
5. **Accept** only if:
   - `|C| == 1`, and  
   - that cross index is in `{n-1, n-2}`  
   **OR** (stricter product choice):  
   - `|C| >= 1`, the **latest** cross is in `{n-1, n-2}`, and **no other cross** exists in the 15d window before it  

Recommended product rule (strict momentum):

```text
ACCEPT if:
  latest_valid_cross.bars_ago in {1, 2}
  AND count(valid_crosses in last 15 days) == 1
```

### Edge cases

| Edge | Handling |
|------|----------|
| Gap up open, EMAs jump | Still use closed-bar rule only for candidates |
| Corporate action / bad data | Invalidate symbol for day if bars missing > threshold |
| Exactly 15d boundary | Use timestamp ≥ now−15d inclusive |
| Multiple crosses same day early | Fail first-cross rule → reject (chop) |

---

## 7. Sideways / rebound filters (extra, ranked)

Apply **after** first-cross + freshness so list stays short.

### P0 (must for v2)

1. First cross in 15 days  
2. bars_ago ∈ {1, 2}  
3. Volume ≥ 1.5×  

### P1 (recommended)

4. **Distance from 200 after cross:**  
   - Bull: close not more than X% already extended from 200 (e.g. 1.5–2.5% on 15m) → avoid chasing  
5. **ATR / range:** cross bar body ≥ 0.5 × 14-ATR(15m) → skip micro wicks  
6. **Prior structure:** in 15d before cross, price spent most time on one side of 200 (e.g. ≥70% closes below 200 for bull first-cross) → true base break  

### P2 (optional)

7. HTF (60m/Daily) not strongly opposing  
8. VWAP side agreement on cross day  
9. Option liquidity min OI/volume on ATM  

---

## 8. 15 days: calendar vs trading bars

| Mode | Definition | Pros |
|------|------------|------|
| **Calendar 15d** | `ts >= now - 15*86400` | Simple, matches user wording |
| **Trading ~15d** | last `15 * 25` 15m bars (~375 bars) | Stable bar count |

**Recommendation:** implement **calendar 15 days** first (user language), with config flag `first_cross_window_days = 15`.

---

## 9. Candidate object (v2 schema)

```json
{
  "symbol": "NSE:CANBK-EQ",
  "name": "CANBK",
  "cross_type": "BULLISH",
  "bars_ago": 1,
  "cross_time": "2026-08-12T13:15:00+05:30",
  "ltp": 102.4,
  "ema7": 101.8,
  "ema200": 101.2,
  "volume_ratio": 2.1,
  "first_cross_in_15d": true,
  "crosses_in_15d": 1,
  "extension_from_200_pct": 0.9,
  "freshness": "FRESH",
  "momentum_score": 0-100,
  "data_mode": "live_bar_close" | "bootstrap_rest",
  "status": "CANDIDATE"
}
```

### Momentum score (idea, not final formula)

```
momentum_score =
  + 40 if bars_ago == 1 else + 25 if bars_ago == 2
  + 30 if first_cross_in_15d
  + min(20, (volume_ratio - 1.5) * 20)
  + 10 if rising volume into cross
  - 15 if extension_from_200_pct > 2.0
```

Sort list by `momentum_score` desc, then `bars_ago` asc.

---

## 10. Option chain step (unchanged philosophy)

Still **not** auto-trade on MA.

On **Analyze Chain** (or auto-queue for FRESH candidates):

### Bullish first-cross → need ≥2

- Call Long Buildup ATM / +1–2  
- Put writing / PE short buildup ATM / below  
- OI PCR > 1 or put-floor regime  
- Max pain > spot  
- Strong ATM CE volume  

### Bearish first-cross → need ≥2

- Put Long Buildup ATM / below  
- Call writing ATM / above  
- OI PCR < 0.85  
- Max pain < spot  
- Strong PE volume / call writing  

Opposite dominant flow → **CONFLICT – AVOID**.

---

## 11. UI / product flow (v2)

### Screen A — Live Momentum Board

| Col | Content |
|-----|---------|
| Stock | Name |
| Side | Bullish / Bearish first-cross |
| Age | **1 bar** / **2 bars** |
| Vol | 2.1× |
| 15d | First ✓ |
| Score | momentum_score |
| Action | Analyze Chain |

Filters:

- Only FRESH (1–2 bars)  
- Only first-in-15d  
- Hide if extension too high  

Banner:

> Showing **first 7/200 cross in 15 days**, age ≤ 2 candles. Older / re-crosses hidden.

### Screen B — Chain result

Same CONFIRMED / NOT_CONFIRMED / CONFLICT + strikes as v1.

### Controls

- **Live** (tick/bar engine)  
- **Reseed REST** (full direct API rebuild of state — current job, ~2 min)  
- Top liquid vs All F&O for reseed only  

---

## 12. Implementation phases (when coding starts)

### Phase 0 — Document freeze (this file)

No code until product agrees on:

- bars_ago exactly `{1,2}`  
- strict `crosses_in_15d == 1`  
- calendar vs trading 15d  

### Phase 1 — Offline rules on existing direct REST scan

- Change detect logic: **only bars_ago 1–2**  
- Add **count crosses in 15d**; keep only first-cross  
- Drop old “any lookback 10” behavior  
- Keep direct API job for full F&O  

**Deliverable:** cleaner list from same REST scanner (no WS yet).

### Phase 2 — State store

- Redis/memory: per symbol last emas, last cross time, 15d cross list  
- Rebuild from REST reseed  

### Phase 3 — Realtime bar close

- Hook 15m bar close from candle aggregator / WS  
- Emit candidates only when rules fire  
- UI websocket or poll candidates endpoint  

### Phase 4 — Tick nearing (optional)

- Distance(EMA7, EMA200) / price < threshold  
- Volume accelerating  
- Nearing table separate from FRESH candidates  

### Phase 5 — Auto chain confirm queue (optional)

- On FRESH first-cross, optionally auto-run OC confirm (rate-limit budget!)  
- Prefer manual Analyze still for control  

---

## 13. Rate-limit & ops notes

| Work | Cost |
|------|------|
| Full reseed 184 × history | ~1.5–2 min paced direct API (already proven) |
| Live bar close only | Low REST; uses WS/aggregator |
| Auto OC on every candidate | High — gate with max N/hour |

Legacy multi-TF MA crossover stays **disabled** so this strategy owns MA quota.

---

## 14. Acceptance criteria (v2 done when)

1. List never shows crosses older than **2 closed 15m candles**.  
2. Every listed name has **exactly one** valid 7/200 cross in the last **15 days**, and it is that fresh one.  
3. Sideways symbols that flip 7/200 multiple times in 15d **do not appear**.  
4. Direct REST reseed still works for full F&O.  
5. Analyze Chain still required for CONFIRMED trade message.  
6. (Phase 3) New first-cross appears within one bar of happening without full reseed.

---

## 15. Open decisions (answer before coding Phase 1)

| # | Question | Suggested default |
|---|----------|-------------------|
| 1 | bars_ago = only `{1,2}` or also forming bar as “pre-alert”? | Candidates `{1,2}` only; nearing separate |
| 2 | 15d calendar or trading bars? | Calendar 15d |
| 3 | Strict `count==1` or allow same-direction continuation? | Strict `count==1` |
| 4 | Max extension from 200 after cross? | 2.0% hard filter P1 |
| 5 | Auto OC confirm? | Manual only first |

---

## 16. One-line product summary

> **Alert only when 7 EMA first breaks 200 EMA in 15 days, on a candle that closed 1–2 bars ago, with volume — then confirm with option chain. No stale crosses, no sideways re-cross spam.**

---

## 17. File / module map (future)

| Piece | Suggested location |
|-------|-------------------|
| Detect + first-cross-15d | `ma7200_scanner.py` (extend) |
| Live engine | `ma7200_live.py` (new) |
| State | Redis keys `optiongreek:ma7200:{symbol}` |
| REST reseed job | existing `/strategies/ma7200/scan/start` |
| Live candidates API | `GET /strategies/ma7200/live` |
| UI | `MA7200Scanner.tsx` — FRESH board |

---

*End of design doc — implementation only after review of §15 decisions.*
