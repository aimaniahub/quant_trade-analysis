# Option Flow Radar — Complete System Document

**Page:** Option Flow Radar (frontend `OptionFlowRadar.tsx`)  
**Date:** 14 August 2026  
**Engine tag:** `v5-mtf` (scan payload)  
**Status:** As implemented in this repo

This is the full working description of the Radar page: what it fetches, how each layer thinks, every numeric parameter, and how a name becomes a **direction**, then an **entry/exit plan**, then a **locked process trade**.

---

## 0. What the page is for

The page answers four questions, in this order:

1. **Is there real option fuel?** (OI × premium × CE/PE, not just volume)  
2. **Which way is allowed?** (Daily + 4H + 1H; 15m only times)  
3. **Where do we enter, target, and get out?** (OI clusters first; pivots/VWAP only confirm)  
4. **Which name do we ride, and when do we stop changing our mind?** (lock + hysteresis)

It does **not** auto-place orders. It produces desk cards.

---

## 1. Files and roles

| Layer | File | Role |
|---|---|---|
| UI | `frontend/components/OptionFlowRadar.tsx` | Tabs, scan poll, process cards, tape, flow detail |
| API client | `frontend/lib/api.ts` | `/radar/*` calls |
| Routes | `backend/app/routes/option_flow_radar.py` | REST + background scan job |
| Scan orchestrator | `backend/app/services/option_flow_radar.py` | Universe, Fyers fetch, one-best-strike, attach process |
| Signal / grade | `backend/app/services/radar_signal_engine.py` | CE/PE matrix, LIS, Greeks, unusual, A+/A/B/C |
| Idea lock | `backend/app/services/idea_engine.py` + `idea_book.py` | Persistence, hysteresis, promote/hold/kill |
| MTF direction | `backend/app/services/mtf_engine.py` + `mtf_service.py` | Daily/4H/1H/15m allowed side |
| Institutional map | `backend/app/services/levels.py` | Pivots, Camarilla, CPR, VWAP, OR, walls |
| OI magnets | `backend/app/services/oi_clusters.py` | Cluster detect, build vs liquidate |
| Execution | `backend/app/services/execution.py` | Entry / stop / target / instrument / action |
| Market I/O | `backend/app/services/fyers_market.py` | Quotes, history, option chain |
| Scheduler | `backend/app/services/radar_scheduler.py` | Background scan every 10 min while open |
| Universe | `backend/app/services/fno_stocks.py` | F&O watchlist |

---

## 2. End-to-end working process

```text
User opens Radar
        │
        ▼
GET /radar/last  ──► paint last board (do not blank the page)
        │
        ▼
POST /radar/scan/start  ──► background job
        │
        ▼
Poll GET /radar/scan/jobs/{id} every 1.5s
        │   (progress bar only; board stays until job COMPLETE)
        ▼
For each symbol (batches of 12):
   spot (light) → option chain → filter/score strikes
        │
        ▼
   If a strike survives:
      5m history (VWAP) + daily OHLC + 4H + 1H + 15m
      + futures quote
      + OI clusters from the same chain
        │
        ▼
   IdeaBook.ingest(snapshot)
        │
        ├── WATCH / CONFLICT / IDLE
        └── ACTIVE (locked process trade)
        │
        ▼
Job done → replace scores/ideas in UI
        │
        ▼
User clicks a card → GET /radar/flow/{symbol}
   (spot/history/chain; falls back to last idea if quote is rate-limited)
```

### 2.1 Role split (non-negotiable)

```text
┌─────────────────────────────────────────────────────────────┐
│  DIRECTION (why / which way)                                │
│  4H + 1H + Daily  → allowed side                            │
│  15m              → timing trigger only (cannot flip side)  │
│  CE/PE matrix     → fuel label (Call Writing = bearish)     │
└─────────────────────────────────────────────────────────────┘
                          │ INPUT only
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  EXECUTION (when / where)                                   │
│  OI clusters      → entry, target, trail/exit               │
│  Tech levels      → secondary confirm only                  │
│  Instrument       → BUY CE if long, BUY PE if short         │
└─────────────────────────────────────────────────────────────┘
```

Levels never vote long vs short. Flow/MTF never pick the target.

---

## 3. How the page fetches data

### 3.1 Frontend scan

| Event | Call | What happens to the board |
|---|---|---|
| Mount | `GET /radar/last` | Paint last completed scan immediately |
| Mount + filter change | `POST /radar/scan/start` | New job; **old cards stay** |
| Poll | `GET /radar/scan/jobs/{id}` every **1.5s** | Progress % + current symbol only |
| Job `completed` | same payload | **Then** replace flagged / ideas / scores |
| Auto refresh | every **90s** | Same as a silent scan |
| Click a name | `GET /radar/flow/{symbol}?strike_count=10` | Detail chain + 5m candles + idea |
| Levels | `GET /radar/levels/{symbol}` | Full institutional map |

If flow quote fails: reuse cache → chain spot → last process idea. Page must not 400-blank.

### 3.2 Per-symbol fetch (scan path)

For **every** watchlist name:

| Step | API | When |
|---|---|---|
| 1. Spot | Fyers `quotes` | Always (light) |
| 2. Option chain | Fyers `optionchain` (`strikecount` default **8** on UI scan, **10** in service default) | Always |

Only if a strike **survives hard filters** (candidate):

| Step | API | Cache |
|---|---|---|
| 3. 5m history | `history` res=`5` days=1 | underlying cache **90s** |
| 4. Daily | `history` res=`D` days=25–30 | levels day-map until next IST date; MTF daily **6h** |
| 5. 4H | `history` res=`240` days=45 | **3 hours** |
| 6. 1H | `history` res=`60` days=15 | **50 min** |
| 7. 15m | `history` res=`15` days=6 | **90s** |
| 8. 3-day option volume | `history` res=`D` days=5 on the option symbol | **1 hour** (top 2 prelims only) |
| 9. Futures | `quotes` on `NSE:{TICKER}{YY}{MON}FUT` | **90s**; OI delta vs last seen |

Batching: **12** symbols, then **0.35s** sleep. Rate-limit abort skips the rest (`partial=true`).

### 3.3 Fyers cache TTLs (`fyers_market.py`)

| Key | TTL |
|---|---|
| Quotes | 3s |
| Spot | 3s |
| Option chain | 8s |
| History (generic) | 45s |
| History 5m / 15m / 30m | 180s |

### 3.4 What a chain row contains (normalized)

From Fyers `optionsChain`, grouped by strike:

```
strike_price
call / put:
  symbol, ltp, oi, oi_change (oich), oi_change_pct (oichp),
  volume, iv, bid, ask, chg (ltpch), chg_pct (ltpchp), prev_oi
  delta, gamma, theta, vega   (Black–Scholes, r=7%)
```

Plus: `spot_price`, `atm_strike`, `pcr`, `india_vix`, `expiries`, `total_call_oi`, `total_put_oi`.

### 3.5 Scheduler (no UI)

While market open: full TOP-FNO scan every **600s** (10 min).  
Closed: check again in **180s**.  
Publishes to signal bus if LIS ≥ **65** (process lock preferred).

Market hours: **09:15–15:30 IST**, weekday, not in holiday list (`market_hours.py`).

---

## 4. Strike scoring pipeline (tape / A-A+)

```text
chain rows
   │
   ├─ ATM distance > 7%          → drop
   ├─ oi==0 or volume==0         → drop
   ├─ |OI change| < 8%           → drop
   ├─ volume < 150               → drop
   ├─ classify_signal == NEUTRAL → drop
   │
   ▼
prelim score = |OI%| × log(volume+1) × (1 + ATM closeness)
   │
   ▼
top 4 → vol spike + full LIS + Greeks + unusual + grade
   │
   ▼
keep if grade ≠ C  OR  unusual alert
   │
   ▼
best one contract per symbol
   (composite, then grade, then LIS, then closer ATM)
```

### 4.1 Hard filters (`radar_signal_engine.py`)

| Parameter | Value | Meaning |
|---|---|---|
| `MAX_ATM_DISTANCE_PCT` | **7.0** | Strike must be within 7% of spot |
| `MIN_OI_CHANGE_PCT` | **8.0** | |ΔOI| vs prior |
| `MIN_PREMIUM_CHG_PCT` | **1.5** | |option LTP %| to count as up/down |
| `MIN_OPTION_VOLUME` | **150** | Absolute volume floor |
| `MIN_VOL_SPIKE` | **1.5** | vs 3-day avg or chain-median peers |
| `MIN_GREEK_QUALITY` | **8 / 20** | Below this, cannot stay grade A |

Vol spike source:

- Prefer **3-day completed daily volume** of that option symbol  
- Else **median volume of near-ATM same-side peers**  
- Hybrid = max of the two  

If real 3-day baseline exists and spike < 1.5× → reject.  
If only chain-median: reject if spike < 1.5 **and** volume < 450 (3× floor).

### 4.2 CE / PE classification (direction of fuel)

Thresholds: OI ±8%, premium ±1.5%.

| Side | OI | Premium | Label | Stock direction |
|---|---|---|---|---|
| CE | ↑ | ↑ | Fresh Call Buying | **BULLISH** |
| CE | ↑ | ↓ | Call Writing | **BEARISH** |
| CE | ↓ | ↑ | Call Short Covering | Mild bull / EXHAUSTION |
| CE | ↓ | ↓ | Call Long Unwinding | Mild bear / EXHAUSTION |
| PE | ↑ | ↑ | Fresh Put Buying | **BEARISH** |
| PE | ↑ | ↓ | Put Writing | **BULLISH** |
| PE | ↓ | ↑ | Put Short Covering | Mild bear / EXHAUSTION |
| PE | ↓ | ↓ | Put Long Unwinding | Mild bull / EXHAUSTION |
| any | ↑ only | flat | Smart Money Accum. | NEUTRAL |
| else | | | Neutral | NEUTRAL |

**Call Writing is bearish.** The written CE is **fuel**, not the contract we buy. Execution later says **BUY PE**.

### 4.3 LIS (Liquidity / Institutional Score, 0–100)

| Piece | Max pts | Formula |
|---|---|---|
| OI | 30 | `min(\|OI%\| / 20, 1) × 30` |
| Volume | 25 | `min((spike−1) / 4, 1) × 25` |
| Momentum | 15 / 12 | Premium move **that agrees with classified direction** (CE up for bull, PE up for bear, writing rewarded at 12) |
| VWAP closeness | 15 | ` (1 − min(\|vwap_dev%\|/2, 1)) × 15 ` |
| EMA20 side | 10 | +10 if bull and above EMA20, or bear and below |
| Delivery | 5 | unused-ish floor (`delivery_ratio` passed as 1.0 → 2.5) |

Cap 100.

### 4.4 Greek quality (0–20) — filter, not signal

| Greek | Points |
|---|---|
| Delta 0.30–0.60 | +8 |
| Delta 0.20–0.30 | +4 |
| Delta > 0.70 | +2 |
| Delta < 0.20 | 0; **reject** if < 0.12 |
| Gamma 0.001–0.05 | +4 |
| Theta ≤ 2 | +3; ≤ 8 → +2; else 0 |
| IV < 35 | +3; < 55 → +2; ≥ 55 → +0.5 |
| ATM ≤ 3% and delta sweet | +2 |

### 4.5 Unusual / Alert Box (0–100)

| Trigger | Points / rule |
|---|---|
| \|OI%\| ≥ 40 | +30 |
| \|OI%\| ≥ 25 | +22 |
| Vol ≥ 5× | +28 |
| Vol ≥ 3× | +22 |
| \|OI added\| ≥ 200k | +20 |
| \|OI added\| ≥ 50k | +14 |
| Premium ≥ 8% and IV ≥ 30 | +10 |
| Cluster ≥ 3 nearby strikes | +12 |

Alert Box if score ≥ **55**, or (OI% ≥ 25 **and** vol ≥ 3×), or (OI added ≥ 150k and vol ≥ 2.5×).

Alert Box is **review only**. It does not auto-promote to a process trade.

### 4.6 Multi-layer grade

Layers: flow, volume, strike, greeks, underlying-not-opposed, unusual.

| Grade | Rule | Product |
|---|---|---|
| **A+** | Required (flow+vol+strike) + greeks + underlying + unusual + LIS≥60 + strong flow | Actionable tape |
| **A** | Required + greeks + underlying + LIS≥50 + strong flow | Actionable tape |
| **B** | Partial | Watch tape |
| **C** | Weak; dropped unless Alert Box | Ignore |

Tape tab **Radar A/A+** shows only A/A+.  
**Watch B** is grade B.  
**Alert Box** is unusual, any grade.

---

## 5. Process lock (stop the 10-second flip)

Unit of the headline is **symbol + direction + zone**, not “best strike this poll.”

### 5.1 Snapshot ring

- One snapshot per symbol when a scan produces a scored contract.  
- If last snapshot is **< 45s** old:  
  - same direction → **overwrite numbers, keep original timestamp**  
  - opposite flicker → **ignore**  
- Neutral scans decay a locked idea’s composite by **× 0.90**.

### 5.2 Persistence

| Parameter | Value |
|---|---|
| Window N | **4** snapshots |
| Need K | **3** same direction |
| Min wall-clock | **180 seconds** |
| Fast path | 2 of last 3 + 180s + no flips, only if location ≥ **6** and grade A/A+ |

### 5.3 Composite (enter / leave)

```
persist×25 + (location/11)×30 + (LIS/100)×25 + (unusual/100)×10
+ 10 if futures agree + 4 if A+ / 2 if A
```

| | Threshold |
|---|---|
| Enter lock | composite ≥ **70** |
| Exit / unlock | composite ≤ **45** (hysteresis) |

### 5.4 Promote to ACTIVE

All of:

- Persistence ready  
- Location ≥ 4 **or** an OI cluster entry exists  
- Fuel is Fresh Buying or Writing (not exhaustion)  
- Recipe ok  
- Composite ≥ 70  
- No hard vetoes  
- Direction BULLISH or BEARISH  
- If MTF is present: `allowed_side` matches, not Daily hard veto, `confirmed_ready` or HQ pullback  

### 5.5 Hard vetoes (new locks only)

| Code | Meaning |
|---|---|
| `OPENING_RANGE` | Before 09:30 IST |
| `LATE_SESSION` | After 15:15 IST |
| `MARKET_CLOSED` | Outside 09:15–15:30 |
| `NO_DIRECTION` | Neutral fuel |
| `EXHAUSTION_FUEL` / `WEAK_FUEL` | Covering / unwind as primary |
| `DELTA_TOO_LOW` | \|Δ\| < 0.20 |
| `FAR_OTM` | ATM dist > 7% |
| `DUAL_SIDE_FLOW` | Both sides printing |
| `HTF_OPPOSE` | Location layer daily oppose |
| `PCR_CEILING` / `PCR_FLOOR` | OI PCR ≤ 0.70 vs long, or ≥ 1.25 vs short |
| `FUTURES_*_BUILDUP` | Futures OI buildup against the idea |
| `EXPIRY_DTE` | **0–2 DTE** — no new confirm |
| `EXPIRY_PIN` | 0–2 DTE + inside Camarilla + near max pain |
| `DAILY_HARD_VETO` | Daily hard opposite of 4H |
| `MTF_SIDE_BLOCK` | 4H allowed side ≠ idea side |
| `MTF_NOT_READY` | Not confirmed and not HQ pullback |
| `NO_LOCATION` | Tech location < 4 and no cluster |
| `DIRECTION_FLIPS` | Ring flipped inside the window |

### 5.6 Lifecycle after lock

```text
ACTIVE
  │
  ├─ 15m unstack                     → HOLD (side unchanged)
  ├─ 1H structure break              → DOWNGRADE to WATCH   frame=H1
  ├─ Supporting OI cluster liquidates→ DOWNGRADE            frame=CHAIN
  ├─ 4H bias / 4H swing break        → KILL                 frame=H4
  ├─ Daily hard veto appears         → KILL                 frame=D
  ├─ Futures opposite buildup        → KILL                 frame=FLOW
  ├─ Composite ≤ 45                  → KILL                 frame=FLOW
  └─ Opposite side persists 180s     → KILL                 frame=FLOW
```

**15m cannot kill or flip a confirmed side.**

Kills/downgrades append `backend/app/data/idea_outcomes.jsonl` with `kill_frame` / `downgrade_frame`.

Strike of the **fuel** print may update quietly (±2 steps). Thesis does not.

---

## 6. MTF direction (allowed side)

Closed candles only (forming bar dropped).

### 6.1 Frames

| Frame | History | Bias tool | Job |
|---|---|---|---|
| Daily | 30d | Close vs 20/50 EMA + HH/HL structure | Soft / **hard veto** if opposite **and** stacked+structured |
| 4H | 45d / res 240 | Same 20/50 + structure | **Owns allowed side** |
| 1H | 15d / res 60 | Close vs 20 EMA + swings | Move still alive / **turning** |
| 15m | 6d / res 15 | 7/20 stack | **Trigger only** |

Daily **MIXED** is allowed.  
Daily **hard** bear + 4H bull → `allowed_side = NONE` (veto).

### 6.2 1H “turning” (exact)

Long: last **closed** 1H close **> 1H 20 EMA** **and** a **higher swing low**.  
Short: last closed close **< 20 EMA** **and** a **lower swing high**.  
No vibe.

### 6.3 Alignment score

Each frame: +1 bull, 0 mixed, −1 bear. Sum −4…+4.

| Label | Meaning | Board |
|---|---|---|
| `FULL_LONG` / `FULL_SHORT` | ±4 + 15m trigger | Confirmed |
| `ALIGNED_*` | ±3 + 15m trigger | Confirmed |
| `HQ_PULLBACK_LONG/SHORT` | ±2 + 1H turning | **High-Quality Pullback** (own lane, ranked so they are not buried) |
| `WATCH_*` | Side allowed, no trigger yet | Watch |
| `DAILY_VETO` / `MIXED` | No trade | Conflict / idle |

### 6.4 Rank (who is the “good” trade)

```
|align| × mom_mult × (1 + location/11) × (0.5 + persist) × chain × pull_boost
```

| Piece | Value |
|---|---|
| Expanding 1H | × 1.15 |
| Compressing (already extended) | × 0.72 |
| HQ pullback | × 1.55 |
| Chain disagrees | × 0.55 |

Board sort: confirmed first, then HQ pullbacks, then watch.

---

## 7. Institutional map (context, not primary magnets)

Computed once per day from previous session H/L/C, plus live session:

| Object | Formula / source |
|---|---|
| Classic P, S1–S3, R1–R3 | Floor pivots `(H+L+C)/3` etc. |
| Camarilla S1–S4, R1–R4, H5/L5 | `C ± (H−L)×1.1/n` |
| CPR TC / BC | `(H+L)/2` and reflection about P |
| PDH / PDL / PDC | Prior day |
| Weekly P | Last ~5 daily H/L/C |
| ATR | 14-day true range |
| VWAP ±1σ/2σ | Today’s 5m typical price |
| Opening range | 09:15–09:30 IST, valid after 09:30 |
| Put / call wall (legacy) | Highest PE OI ≤ spot; highest CE OI ≥ spot |
| Max pain, gamma wall, PCR | `option_analytics.py` |

Camarilla regime: inside S3–R3 = range; above R4 = trend up; below S4 = trend down.

Location score (0–11) still used as a **soft** confluence vote (pivot + wall + VWAP + Cam + HTF + MA + CPR + weekly + cluster zone). It does **not** pick the target.

---

## 8. OI clusters (primary entry / exit)

### 8.1 How a cluster is built

From the **same** option chain just fetched:

1. Collect every CE and PE with OI > 0 (strike, OI, ΔOI%, volume, premium %).  
2. Median OI of all legs.  
3. A strike is “hot” if `OI ≥ max(median × 1.55, 8_000)`.  
4. Merge neighbours within **2 strike steps**.  
5. Cluster centre = OI-weighted strike; peak = max-OI strike.

| Parameter | Value |
|---|---|
| `MIN_CLUSTER_OI` | 8,000 |
| `MIN_MULT_VS_MEDIAN` | 1.55× |
| `MERGE_STEPS` | 2 |

Health:

| Health | Rule |
|---|---|
| **BUILDING** | ΔOI ≥ +8% and premium ≤ −1.5% (writers defending) |
| **ADDING** | ΔOI ≥ +8% |
| **LIQUIDATING** | ΔOI ≤ −8% and premium ≥ +1.5% (shorts covering) |
| **UNWINDING** | ΔOI ≤ −8% |
| **STABLE** | else |

Call cluster = **resistance / supply**.  
Put cluster = **support / demand**.

### 8.2 Entry and target (given direction)

| Side | Entry | Target | T2 |
|---|---|---|---|
| Long | Nearest **put** cluster at or **below** spot (skip liquidating if another exists) | Nearest **call** cluster **above** | Next call cluster further up |
| Short | Nearest **call** cluster at or **above** spot | Nearest **put** cluster **below** | Next put cluster further down |

Stop: **0.15 × ATR** beyond the supporting cluster.  
A resistance cluster is **never** a short target.

If no cluster exists, fall back to the old tech map (put wall / S1 / Cam / VWAP). UI marks `Magnet: OI cluster` vs `tech backup`.

If VWAP / P / S1 / R1 / Cam S3/R3 sits within **0.25 ATR** of the cluster → `tech_confirm` tags only.

### 8.3 Idea dying (trail, do not reverse)

If the **supporting** cluster (put cluster for a long, call cluster for a short) is **LIQUIDATING**:

- Execution action → **TRAIL_EXIT**  
- Idea **downgraded** to WATCH  
- `downgrade_frame = CHAIN`  
- Side is **not** flipped to the other direction

---

## 9. Execution actions (when to click)

Direction is already known. Execution only says:

| Action | Meaning |
|---|---|
| `WAIT_FOR_LEVEL` | Long: wait dip to put cluster. Short: wait rally into call cluster |
| `AT_ENTRY` | Spot within **0.30 ATR** of entry — take it |
| `CHASE` | Already ran **0.45 ATR** past entry — do not chase |
| `IN_TRADE` | Locked, between entry and T1 — hold |
| `HIT_T1` / `HIT_T2` | Bank / trail |
| `STOPPED` | Through stop |
| `TRAIL_EXIT` | Supporting cluster liquidating |

Once **ACTIVE**, entry / stop / T1 **do not wander**. Only the action state updates.

### 9.1 Instrument (what we buy)

| Direction | Buy | Strike |
|---|---|---|
| Long | **CE** | Rounded to step nearest **entry** (not the fuel CE) |
| Short | **PE** | Same, even if fuel was Call Writing on a CE |

Fuel print (e.g. 2100 CE writing) stays labeled **fuel**. Card headline strike is the **PE/CE to buy**.

Strike step: ≥20k→100, ≥5k→50, ≥2k→20, ≥1k→10, ≥250→5, else 2.5.

---

## 10. UI map (what each tab is)

| Tab | Content |
|---|---|
| **Process** | Locked / HQ pullback / watch / conflict. Direction stamp + execution plan. Default tab. |
| **Tape A/A+** | Graded flow tape (does not replace Process) |
| **Alert Box** | Unusual size, not auto-trade |
| **Watch B** | Grade B tape |
| **Stock Flow Detail** | Idea + levels strip + 5m candles + chain. Stays up if live quote fails. |
| **Signal Log** | Session flags + backtest |

Process card layout:

- **BULLISH SIGNAL / BEARISH SIGNAL / NO TRADE**  
- D / 4H / 1H / 15m stamps, `15m TRIGGER`, `1H TURNING`, align score  
- **Direction (why)** = fuel label + fuel strike  
- **Execution (when/where)** = WAIT / AT_ENTRY / CHASE / TRAIL + R:R + magnet source  
- Entry / stop / T1 / T2 with cluster names  
- Buy-this strike = PE or CE from execution  

Scan **does not clear** this board. Scores swap when the job finishes.

---

## 11. REST surface

| Method | Path | Use |
|---|---|---|
| GET | `/api/v1/radar/watchlist` | Universe |
| GET | `/api/v1/radar/last` | Last scan + ideas (first paint) |
| GET | `/api/v1/radar/scan` | Blocking scan (legacy) |
| POST | `/api/v1/radar/scan` | Custom symbol list |
| POST | `/api/v1/radar/scan/start` | Background job |
| GET | `/api/v1/radar/scan/jobs/{id}` | Poll |
| GET | `/api/v1/radar/flow/{symbol}` | Detail |
| GET | `/api/v1/radar/candles/{symbol}` | OHLCV |
| GET | `/api/v1/radar/ideas` | Process board |
| GET | `/api/v1/radar/ideas/{symbol}` | One idea |
| GET | `/api/v1/radar/levels/{symbol}` | Full map |
| POST | `/api/v1/radar/backtest` | Forward 15/30/60m returns |

Prefix: `NEXT_PUBLIC_API_URL` or `http://localhost:8000/api/v1`.

---

## 12. Parameter cheat-sheet

### Fetch / scan

| Name | Value |
|---|---|
| UI strike_count | 8 |
| Detail strike_count | 10–12 |
| Batch size | 12 |
| Batch sleep | 0.35s |
| Job poll | 1.5s |
| Auto refresh | 90s |
| Scheduler open | 600s |
| Underlying cache | 90s |
| Vol cache | 3600s |
| 4H / 1H / 15m / Daily MTF TTL | 3h / 50m / 90s / 6h |

### Fuel / tape

| Name | Value |
|---|---|
| ATM max | 7% |
| OI change | 8% |
| Premium | 1.5% |
| Min volume | 150 |
| Vol spike | 1.5× |
| Alert OI / vol / score | 25% / 3× / 55 |

### Lock

| Name | Value |
|---|---|
| Snapshot gap | 45s |
| Persist | 3 of 4 and ≥ 180s |
| Enter / exit composite | 70 / 45 |
| Location min | 4 (or cluster) |
| New confirm blackout | 09:15–09:30 and after 15:15 |
| Expiry | no new lock if DTE ≤ 2 |

### Clusters

| Name | Value |
|---|---|
| Median multiple | 1.55× |
| Min OI | 8,000 |
| Merge | 2 steps |
| Build | +8% OI and −1.5% prem |
| Liquidate | −8% OI and +1.5% prem |
| At-zone / chase | 0.30 ATR / 0.45 ATR |
| Stop pad | 0.15 ATR |

---

## 13. Worked example (short)

1. **4H + 1H bearish**, Daily not hard-bull → allowed **SHORT**.  
2. Chain: 2140 CE OI huge and building (writers) → **Call cluster 2140** = resistance.  
3. 2000 PE OI huge → **Put cluster 2000** = target.  
4. Fuel: 2100 CE, OI↑ premium↓ → **Call Writing** (bearish). That CE is fuel, not the buy.  
5. 15m 7<20 closes → trigger. Persist 3+ minutes. Composite ≥ 70.  
6. **ACTIVE SHORT.** Buy **PE** near 2140. Stop above 2140 + 0.15 ATR. T1 = 2000 put cluster.  
7. If 2140 CE OI starts falling and premium rises → **TRAIL_EXIT**, downgrade. Do **not** flip long.  
8. Only a **4H** close against us kills the side.

---

## 14. What each number on the card means

| You see | Comes from |
|---|---|
| BULLISH / BEARISH SIGNAL | Idea direction (MTF + CE/PE), not the last LIS tick |
| D / 4H / 1H / 15m stamps | Closed-bar MTF biases |
| Fuel 2100 CE | The option that proved the flow |
| Buy 2140 PE | Execution instrument |
| Entry Call cluster 2140 | Supporting OI cluster |
| Target Put cluster 2000 | Opposing OI cluster |
| Magnet: OI cluster | Cluster won over Cam/pivot |
| confirm VWAP+R1 | Tech sits on that cluster |
| R:R | (spot→T1) / (spot→stop) |
| LOCKED | Hysteresis ACTIVE |
| HIGH-QUALITY PULLBACK | Align ±2 + 1H turning |
| Supporting cluster dying | Liquidation trail |

---

## 15. Failure / fallback behaviour

| Failure | Behaviour |
|---|---|
| Fyers not authenticated | Scan returns error; UI shows it |
| Rate limit mid-scan | `partial`, remaining symbols skipped |
| No candidate on a name | Neutral snapshot (decays lock) |
| MTF history missing | MTF vetoes skipped (cannot confirm side from empty data) |
| No OI cluster | Tech walls/pivots used; magnet = tech backup |
| Spot quote fail on detail | Cache → chain spot → last idea; warning, not blank |
| Dual-side unusual | CONFLICT / no trade |

---

## 16. Related design notes (not this page’s runtime)

| Doc | Topic |
|---|---|
| `flow.md` | Why 10s flicker is wrong; lock philosophy |
| `MTF_Momentum_README.md` | Why 4H owns side, 15m cannot flip |
| `Option_Flow_Radar_Complete_Specification_v3.txt` | Original CE/PE + grade spec |
| `flow fix.md` | Early classify_signal diagnosis |

---

**One-line system:**  
Scan the chain for real CE/PE fuel → allow a side only if Daily/4H/1H agree → enter at the supporting OI cluster, target the opposing cluster, trail when that cluster liquidates → lock that campaign until a **higher** frame or the cluster itself dies.
