# Flow Radar — Fresh 3-Phase Implementation Plan
## Phase 1 README: Stop the Bleeding + Establish a Clean Baseline

**Project:** `quant_trade-analysis` (OptionGreek)  
**Date:** 20 August 2026  
**Primary product:** Flow Radar  
**Goal:** Fast F&O data fetch + fast analysis, with no unnecessary Fyers calls, duplicate scans, false quota cooldowns, or hidden UI work stealing the market-data budget.

---

# 1. Phase 1 Objective

Phase 1 is NOT about making the scanner maximally fast yet.

Phase 1 is about making the system **correct, predictable, observable, and single-owner** before adding concurrency.

### Phase 1 success condition

After Phase 1:

- Flow Radar is the only active market-data writer.
- No false 429/quota cooldowns caused by generic JSON/network errors.
- Home/dashboard polling cannot steal Fyers requests while Radar is active.
- Scheduler and manual Scan cannot start competing full-universe walks.
- Radar displays symbols incrementally while scanning.
- Partial results are valid and visible.
- A row click does not perform duplicate option-chain requests.
- Existing signal/scoring logic is untouched.
- The system has enough logging/tests to prove the above.

**Important:** Do not increase request concurrency in Phase 1. That belongs to Phase 2.

---

# 2. The Problem We Are Fixing

The existing architecture has a good signal engine but the I/O path is wasting the scarce Fyers budget.

The major problems identified in the architecture analysis are:

1. Option-chain harvesting is serial.
2. False quota detection treats errors such as `Expecting value` and `max retries exceeded` as rate limits.
3. A single failed symbol can trigger multiple long waits.
4. The UI hides useful results until the whole 187-symbol universe finishes.
5. A process-global harvest-writer flag makes unrelated HTTP handlers behave like harvest writers.
6. The hidden Home page remains mounted and continues polling.
7. Scheduler and manual Scan can represent two competing harvest mechanisms.
8. History is mixed into the chain critical path.
9. `get_symbol_flow` can fetch the same option chain twice.
10. Other pages can still escape to Fyers when the store misses.

The source architecture identifies these as the main causes of lag and incomplete listing. See the original diagnosis and root-cause sections in the architecture document.

---

# 3. Target Architecture for the Entire Project

We will rebuild toward this architecture in three phases.

```text
                         ┌──────────────────┐
                         │      Fyers       │
                         │ REST + WebSocket │
                         └────────┬─────────┘
                                  │
                         ┌────────▼────────┐
                         │  MARKET GATEWAY  │
                         │                  │
                         │ Rate limiter     │
                         │ Single-flight    │
                         │ Quota protection │
                         │ One REST writer  │
                         └────────┬─────────┘
                                  │
                     ┌────────────▼────────────┐
                     │       SYMBOL BOOK       │
                     │      Redis + Memory     │
                     │                         │
                     │ spot / chain / history  │
                     │ derived / futures       │
                     │ radar / timestamps      │
                     └────────────┬────────────┘
                                  │
                 ┌────────────────┼────────────────┐
                 │                │                │
                 ▼                ▼                ▼
           Flow Radar          History          WebSocket
           Signal Engine       Sweeper           Spots
                 │
                 ▼
           Live Radar Board
                 │
                 ▼
              Frontend
```

## Core architectural law

> **Only the Market Gateway may perform market-data REST calls to Fyers.**

Everything else should read from the Symbol Book.

This is the final architecture. Phase 1 uses a safer transition mechanism; Phase 3 can enforce the boundary fully.

---

# 4. Three-Phase Roadmap

## PHASE 1 — Stop the Bleeding + Correct the Data Flow

**Goal:** Make Radar correct and predictable before optimizing speed.

### Deliverables

- Correct rate-limit classification.
- No false cooldowns.
- Writer isolation.
- Store-first reader behavior.
- Home polling disabled while Radar is active.
- One harvest owner.
- Incremental board updates.
- Partial scans visible.
- Scheduler/manual scan coordination.
- Duplicate chain fetch removed.
- Baseline instrumentation and tests.

### Expected result

Radar may still be slower than the final target, but it will no longer waste requests or hide valid results.

---

## PHASE 2 — Fast Chain Harvest

**Goal:** Make the actual F&O chain collection fast.

### Deliverables

- Four concurrent chain workers.
- Shared limiter around ~3 RPS sustained.
- Priority queue.
- TOP 34 first.
- Remaining 153 after priority tier.
- One short retry.
- No long retry loops.
- 8-second per-symbol timeout.
- History removed from the chain critical path.
- Batched futures quotes.
- Incremental publishing remains enabled.

### Target

```text
TOP 34       <= 15 sec
All 187      <= 75 sec
No cooldown  during normal clean harvest
```

Concurrency hides HTTP latency; it does NOT increase the sustained request rate beyond the safe budget.

---

## PHASE 3 — Persistent Live Market Book

**Goal:** Make the entire application store-driven and restart-safe.

### Deliverables

- Redis enabled.
- Fyers WebSocket drives live LTP/volume.
- 187 F&O underlyings subscribed.
- History sweeper separated from Radar.
- Row click reads store.
- Store-only Home/Quant/VAT/HV/7/200/confluence paths.
- Canonical chain width.
- Single-flight cache.
- Full Market Gateway boundary.
- Production health/quota telemetry.
- Final live-desk frontend behavior.

### Final target

```text
<= 15 sec   TOP 34 visible
<= 75 sec   all 187 attempted
< 1 sec     live spot updates through WS
0           unnecessary duplicate OC requests
0           normal quota cooldowns
<= 180 RPM  operational budget
```

---

# 5. PHASE 1 — Exact Implementation Plan

## Step 0 — Freeze Product Logic

Before touching performance code:

DO NOT modify:

- CE/PE classification.
- OI logic.
- LIS.
- Greek quality.
- Grade logic.
- Idea lock/hysteresis.
- OI clusters.
- Entry/stop/target.
- MTF scoring.
- Desk score.
- Signal engine thresholds.

These are not the primary performance problem.

Only modify the I/O, scheduling, storage, job, and frontend listing layers.

---

# 6. Phase 1.1 — Fix Rate-Limit Detection

## File

`backend/app/services/rate_limiter.py`

## Current problem

The rate-limit detector currently treats:

```text
Expecting value
max retries exceeded
```

as quota errors.

These are not sufficient evidence of a Fyers quota violation.

## Change

Only classify errors such as:

```text
429
request limit
rate limit
too many requests
quota exceeded
```

as rate-limit events.

## Rule

```python
def is_rate_limit_error(error):
    text = str(error).lower()

    return (
        "429" in text
        or "request limit" in text
        or "rate limit" in text
        or "too many requests" in text
        or "quota exceeded" in text
    )
```

Do not blindly copy this implementation if the existing function has structured response/code information; preserve better structured checks where available.

## Acceptance test

```text
"Expecting value"          -> NOT quota
"max retries exceeded"     -> NOT quota
HTTP 429                   -> quota
"request limit exceeded"   -> quota
"quota exceeded"           -> quota
```

---

# 7. Phase 1.2 — Remove the Global Writer Problem

## File

`backend/app/services/symbol_store.py`

## Current problem

The current implementation uses a process-global depth counter.

That means:

```text
Radar harvest starts
        ↓
global writer = true
        ↓
Home request arrives
        ↓
Home thinks it is allowed to call Fyers
```

This is exactly what we do not want.

## Phase 1 transition fix

Use thread-local writer state.

Concept:

```python
_tls = threading.local()

@contextmanager
def harvest_writer():
    depth = getattr(_tls, "depth", 0)
    _tls.depth = depth + 1

    try:
        yield
    finally:
        _tls.depth = max(
            getattr(_tls, "depth", 1) - 1,
            0
        )

def is_harvest_writer():
    return getattr(_tls, "depth", 0) > 0
```

## Important

The harvest worker thread is the writer.

FastAPI request threads are readers.

This prevents a Radar harvest from granting writer privileges to unrelated request handlers.

---

# 8. Phase 1.3 — Store-First Reader Hard Mode

## Files

- `fyers_market.py`
- `config.py`

## Add configuration

```env
FYERS_READER_ESCAPE=false
```

Default:

```text
false
```

## Reader rule

If an HTTP route is not the harvest writer:

```text
store hit
    ↓
return store

store miss
    ↓
return stale data OR store_miss
    ↓
DO NOT call Fyers
```

Do not let normal UI/API readers escape to Fyers.

## Why

Otherwise:

```text
Radar harvest
      +
Home
      +
Confluence
      +
Flow click
      +
Quant
```

all compete for the same Fyers quota.

---

# 9. Phase 1.4 — Disable Hidden Home Polling

## Files

- `Dashboard.tsx`
- Home market-data hooks/components

## Current problem

Home remains mounted with CSS hidden.

Therefore its queries continue running.

Known pollers include:

```text
MarketStateDetector      45s
ActiveStrategy            45s
OptionChainTable          45s
MarketIndices             45s
ConfluencePanel           60s
```

## Required change

Preferred:

```text
Unmount Home when leaving Home
```

OR:

```text
enabled: currentView === "dashboard"
```

for every Home market-data query.

## Acceptance test

Switch:

```text
Home → Radar
```

Wait 60 seconds.

Expected:

```text
Home Fyers requests = 0
```

---

# 10. Phase 1.5 — One Harvest Owner

## Files

- `radar_scheduler.py`
- `routes/option_flow_radar.py`
- `option_flow_radar.py`

## Current problem

There are two possible full scans:

```text
RadarScheduler
      ↓
scan_all()

Manual Scan
      ↓
scan_all()
```

This is dangerous.

## New rule

There is exactly one harvest actor.

```text
Scheduler
   ↓
Harvest actor
   ↓
scan_all
```

Manual Scan becomes:

```text
POST /radar/scan/start
        ↓
nudge current actor
        ↓
if idle → start one pass
if running → do NOT start another
```

## Never allow

```text
scan_all()
scan_all()
```

at the same time.

---

# 11. Phase 1.6 — Scheduler Must Have a Scan Job

The scheduler currently operates outside the normal ScanJob lifecycle.

Fix this.

Every scheduler harvest must have:

```json
{
  "job_id": "...",
  "status": "running",
  "phase": "chains",
  "scanned": 20,
  "total": 187
}
```

The frontend must be able to observe the exact same job whether the harvest was started automatically or manually.

---

# 12. Phase 1.7 — Incremental Board Publishing

## Current problem

The engine can already have useful per-symbol results in memory, but the API/frontend hides them until completion.

This is one of the biggest UX bugs.

## New rule

After each completed symbol:

```text
fetch
 ↓
score
 ↓
upsert symbol
 ↓
publish board
```

Do NOT wait for:

```text
187 / 187
```

## Board state

Example:

```json
{
  "phase": "chains",
  "scanned": 27,
  "total": 187,
  "partial": true,
  "flagged": [],
  "watch": [],
  "alert_box": [],
  "errors": [],
  "skipped": []
}
```

This is a valid board.

---

# 13. Phase 1.8 — Separate Fetch Status from Signal Status

Introduce explicit symbol state.

Recommended model:

```text
FETCHING
SUCCESS
NO_SIGNAL
SKIPPED
ERROR
STALE
```

And separately:

```text
A+
A
B
C
NO_SIGNAL
```

This prevents a symbol with no trading opportunity from being confused with a symbol that failed to fetch.

Example:

```text
RELIANCE   SUCCESS   A
INFY       SUCCESS   NO_SIGNAL
TCS        SKIPPED   —
SBIN       ERROR     —
```

The UI should be able to list all four.

---

# 14. Phase 1.9 — Fix Partial Scan Semantics

Do not use:

```text
scanned == total
```

as a synonym for data quality.

Track:

```text
attempted
ok_chain
hits
skipped
errors
```

Example:

```json
{
  "attempted": 187,
  "ok_chain": 181,
  "hits": 23,
  "skipped": 4,
  "errors": 2,
  "partial": true
}
```

Suggested definition:

```python
partial = ok_chain < total
```

But the UI should still display the board.

---

# 15. Phase 1.10 — Fix get_symbol_flow Double Fetch

## File

`option_flow_radar.py`

Current flow:

```text
get_symbol_flow
    ↓
get_option_chain
    ↓
_process_option_chain
    ↓
get_option_chain AGAIN
```

Fix:

```python
chain_resp = self.market_service.get_option_chain(
    symbol,
    strike_count
)

best = self._process_option_chain(
    symbol,
    underlying,
    strike_count,
    chain_resp=chain_resp
)
```

## Acceptance test

After a warm harvest:

```text
click row
↓
0 additional optionchain Fyers requests
```

---

# 16. Phase 1.11 — Add Baseline Telemetry

Before Phase 2 concurrency, record:

```text
harvest_id
symbol
priority
queue_time
request_start
request_end
latency
status
retry_count
quota_wait
cache_hit
signal_time
```

At the harvest level:

```text
total_symbols
attempted
successful
skipped
errors
hits
elapsed_ms
Fyers requests
429 count
cooldown count
```

This is mandatory.

Do not optimize blindly.

---

# 17. Phase 1.12 — Add Health/Quota Visibility

Expose:

```json
{
  "radar": {
    "running": true,
    "phase": "chains",
    "scanned": 42,
    "total": 187
  },
  "fyers": {
    "requests_last_minute": 73,
    "limit": 200,
    "cooldown": false,
    "429_count": 0
  }
}
```

The frontend should eventually show:

```text
Radar
━━━━━━━━━━━━━━━━━━
42 / 187
Phase: Chains

Fyers
━━━━━━━━━━━━━━━━━━
73 / 200 RPM
🟢 Healthy
```

---

# 18. Phase 1.13 — Tests

Before Phase 1 is considered complete:

### Test 1 — False quota

```text
Expecting value
```

must not trigger cooldown.

### Test 2 — Real quota

```text
429
```

must trigger quota handling.

### Test 3 — Writer isolation

During a harvest:

```text
fake HTTP request from another thread
```

must not become a Fyers writer.

### Test 4 — Home isolation

While Radar is active:

```text
Home Fyers requests = 0
```

### Test 5 — Incremental listing

After 10 symbols:

```text
scanned = 10
```

and their results must be visible.

### Test 6 — Partial

20 failed symbols must still produce a visible board.

### Test 7 — Single harvest

Scheduler running + manual Scan:

```text
number of scan_all executions = 1
```

### Test 8 — Row click

Warm store:

```text
additional Fyers grants = 0
```

---

# 19. Files Expected to Change in Phase 1

Primary files:

```text
backend/app/services/rate_limiter.py
backend/app/services/symbol_store.py
backend/app/services/fyers_market.py
backend/app/services/option_flow_radar.py
backend/app/services/radar_scheduler.py
backend/app/api/routes/option_flow_radar.py
backend/app/core/config.py
frontend/.../Dashboard.tsx
frontend/.../OptionFlowRadar.tsx
frontend/.../api.ts
```

Use the actual repository paths if the current tree differs.

Do not modify signal-engine logic unless a test proves it is required for Phase 1.

---

# 20. Phase 1 Definition of Done

Phase 1 is complete only when all are true:

- [ ] No false cooldown from `Expecting value`.
- [ ] No false cooldown from generic retry errors.
- [ ] Real 429 still triggers protection.
- [ ] Writer state is isolated.
- [ ] Normal readers cannot escape to Fyers.
- [ ] Home polling stops outside Home.
- [ ] Scheduler and manual Scan share one harvest.
- [ ] Scheduler has a visible ScanJob.
- [ ] Results appear incrementally.
- [ ] Partial scans remain visible.
- [ ] Fetch state and signal state are separate.
- [ ] `get_symbol_flow` does not double-fetch OC.
- [ ] Baseline telemetry exists.
- [ ] Quota health is visible.
- [ ] Tests pass.

---

# 21. What NOT to Do in Phase 1

DO NOT:

- Increase workers to 4 yet.
- Set limiter to 10 RPS.
- Add more cache layers.
- Rewrite the signal engine.
- Add 5m history to the harvest.
- Add 3-day option history.
- Start another scanner.
- Add another Fyers client.
- Make frontend components call Fyers directly.
- Make every page “live” independently.
- Optimize CPU before I/O ownership is fixed.

Phase 1 is about correctness and ownership.

---

# 22. Phase 2 Preview

After Phase 1 passes:

```text
4 workers
+
~3 RPS sustained
+
priority queue
+
TOP 34 first
+
one retry
+
8s timeout
+
history removed from critical path
```

Target:

```text
TOP 34       <= 15 sec
187 chains   <= 75 sec
```

Phase 2 is where the actual major speed improvement happens.

---

# 23. Phase 3 Preview

After Phase 2:

```text
Redis ON
+
WebSocket spots
+
history sweeper
+
store-only readers
+
Market Gateway boundary
+
restart-safe book
```

Target:

```text
Fast fetch
Fast analysis
Live LTP
No duplicate requests
No competing pages
Restart-safe state
```

---

# 24. Final Operating Model

The finished system should behave like this:

```text
09:15
  │
  ▼
Harvest starts
  │
  ├── TOP priority chains
  │       ↓
  │    Board updates immediately
  │
  ├── Remaining F&O chains
  │       ↓
  │    Board continues updating
  │
  ├── History runs separately
  │
  └── WebSocket continuously updates spot
          │
          ▼
      Symbol Book
          │
          ├── Flow Radar
          ├── Home
          ├── Quant
          ├── VAT
          ├── HV
          └── 7/200
```

The central principle is:

> **Fetch once, store once, analyze many times.**

Not:

> Fetch separately for every page and every feature.

---

# 25. Phase 1 Deliverable

At the end of Phase 1, the application should feel **correctly wired**, even before maximum speed optimization:

```text
Fyers
  ↓
ONE controlled harvest
  ↓
187-symbol book
  ↓
incremental Radar board
  ↓
fast local analysis
```

Then Phase 2 makes the fetch fast.

Then Phase 3 makes the whole application persistent and live.

---

# Source Architecture Basis

This Phase 1 plan is derived from the supplied architecture analysis, particularly its diagnosis of serial harvesting, false quota detection, hidden UI polling, global writer state, duplicate harvests, incremental listing requirements, and the ordered PR strategy. The original architecture explicitly identifies Flow Radar as the priority product and sets the 187-name completeness requirement, 20-second first-useful-board target, 90-second full-book target, and 200 RPM / 10 RPS Fyers constraints.

The original architecture also states that signal/scoring logic is not the bottleneck and should remain intact while the I/O schedule and listing contract are fixed.
