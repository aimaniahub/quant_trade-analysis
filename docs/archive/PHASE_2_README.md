# Flow Radar — Fresh 3-Phase Implementation Plan
## Phase 2 README: Fast Chain Harvest + Fast Analysis

**Project:** `quant_trade-analysis` (OptionGreek)  
**Phase:** 2 of 3  
**Primary goal:** Fetch the complete F&O option-chain universe quickly and make analysis available immediately without unnecessary REST work.

---

# 1. Phase 2 Objective

Phase 1 established correctness and ownership.

Phase 2 is where we make the **actual market-data harvest fast**.

The target is:

```text
TOP 34      <= 15 seconds
ALL 187     <= 75 seconds
```

while keeping the operational Fyers budget around:

```text
180 requests/minute
~3.0 sustained requests/second
<=10 requests/second burst ceiling
```

The critical idea is:

> **Increase concurrency to hide network latency, NOT to increase the Fyers request rate.**

The existing architecture analysis explicitly identifies serial harvesting as the main latency problem and proposes 4 workers with a ~0.33s limiter interval. Phase 2 implements that speedup.

---

# 2. What Phase 2 Assumes

Phase 2 must NOT start until Phase 1 is complete.

Required Phase 1 conditions:

- One harvest owner.
- No competing `scan_all`.
- No false quota cooldowns.
- Store-first readers.
- Home polling disabled outside Home.
- Incremental board publishing.
- Partial boards are valid.
- Scheduler and UI use the same harvest job.
- `get_symbol_flow` no longer double-fetches option chains.
- Baseline telemetry exists.
- Phase 1 tests pass.

If any of these are still broken, fix Phase 1 first.

---

# 3. Current Speed Problem

The current implementation effectively behaves like:

```text
187 symbols
   │
   ▼
worker 1
   │
   ├── wait for limiter
   ├── HTTP option chain
   ├── wait for response
   ├── process
   ├── next symbol
   │
   └── repeat
```

If one option-chain request takes approximately 0.8–1.5 seconds, serial execution wastes most of the available Fyers request budget.

The old architecture estimated roughly 0.7–1.2 names/second on the serial path.

The solution is not:

```text
10 RPS
```

because the 200/minute cap would be exceeded.

The solution is:

```text
4 concurrent HTTP workers
+
shared ~3 RPS limiter
```

So while one request waits on network latency, another request can use the already-approved budget slot.

---

# 4. Phase 2 Target Architecture

```text
                    Harvest Actor
                         │
                         ▼
                 ┌───────────────┐
                 │ Priority Queue│
                 └───────┬───────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
          Worker 1    Worker 2   Worker 3   Worker 4
              │          │          │          │
              └──────────┼──────────┘
                         ▼
                  Shared Limiter
                         │
                    ~3.0 RPS
                         │
                         ▼
                       Fyers
                         │
                         ▼
                   Symbol Book
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
          CPU scoring            Live Board
              │                     │
              └──────────┬──────────┘
                         ▼
                      Radar
```

### Important

The workers are concurrent.

The Fyers request budget is still globally controlled.

There must be exactly **one shared limiter**.

Do not create one limiter per worker.

---

# 5. Phase 2.1 — Change Chain Worker Concurrency

## File

`backend/app/services/option_flow_radar.py`

## Current

The existing architecture identifies:

```python
ThreadPoolExecutor(max_workers=1)
```

## Target

Use:

```python
ThreadPoolExecutor(max_workers=4)
```

The exact implementation must preserve the existing `scan_one` behavior and error handling established in Phase 1.

Conceptually:

```python
with ThreadPoolExecutor(max_workers=4) as pool:
    futures = [
        pool.submit(_scan_one, symbol)
        for symbol in priority_symbols
    ]

    for future in as_completed(futures):
        result = future.result()
        _upsert_board(result)
```

Do not blindly use this snippet if the existing function has ordering/job semantics that must be preserved.

---

# 6. Why Four Workers?

Four workers are enough to overlap normal network latency while keeping the system simple.

Example:

```text
HTTP latency = 1.0 sec

1 worker:
1 request completes ≈ every 1 sec

4 workers:
multiple requests can be in-flight
while the limiter still controls starts
```

The limiter remains the quota authority.

Do NOT solve the problem by creating:

```text
worker 1 → limiter 1
worker 2 → limiter 2
worker 3 → limiter 3
worker 4 → limiter 4
```

That can multiply the effective rate and break the Fyers budget.

---

# 7. Phase 2.2 — Configure the Shared Limiter

## File

`backend/app/services/rate_limiter.py`

Target operational configuration:

```text
FYERS_RPM = 180
CHAIN_RPS = 3.0
```

Equivalent approximate interval:

```text
1 / 3.0 = 0.333 seconds
```

So:

```text
min_interval ≈ 0.33 sec
```

The architecture intentionally leaves approximately 20 requests/minute of headroom below the 200 RPM Fyers limit.

---

# 8. Do Not Set 10 RPS

Never do:

```python
min_interval = 0.1
```

because:

```text
10 requests/sec
×
60 sec
=
600 requests/minute
```

That is incompatible with the 200/minute cap.

Even if a short burst appears to work, the minute-level limit will eventually cause throttling.

The speed lever is:

```text
concurrency ↑
```

not:

```text
allowed request rate ↑
```

---

# 9. Phase 2.3 — Priority Queue

The 187 symbols must NOT be processed randomly.

Use tiers.

## Priority model

```text
P0 — Highest
├── Locked ideas
├── Previous A+ hits
└── Previous A hits

P1 — Product-critical
├── NIFTY
├── BANKNIFTY
├── FINNIFTY
└── TOP 31 F&O stocks

P2 — Complete universe
└── Remaining F&O stocks

P3 — Recovery
└── Previously failed/skipped symbols
```

The effective TOP tier is:

```text
31 stocks + 3 indices = 34
```

---

# 10. Priority Queue Rules

At the beginning of each harvest:

1. Load previous board.
2. Identify locked ideas.
3. Identify previous A+/A symbols.
4. Add the three indices.
5. Add TOP 31.
6. Add remaining symbols.
7. Add previously failed symbols in the recovery tier.

Do not duplicate a symbol across tiers.

Use a single ordered queue.

---

# 11. Phase 2.4 — TOP 34 Must Win the Race

The product requirement is not simply:

```text
187 symbols fast
```

It is:

```text
important symbols first
+
complete universe shortly after
```

Target:

```text
0–15 sec
    ↓
TOP 34 visible

15–75 sec
    ↓
remaining universe
```

The board must update as each TOP symbol completes.

Do not wait for all 34.

---

# 12. Phase 2.5 — Per-Symbol Retry Policy

The old design allowed:

```text
up to 6 attempts
+
4–45 second waits
```

That is not acceptable on the hot path.

Phase 2 target:

```text
Attempt 1
   ↓
failure
   ↓
short backoff ~1.5 sec
   ↓
Attempt 2
   ↓
failure
   ↓
SKIPPED
```

Maximum:

```text
1 retry
```

Then move on.

A single bad symbol must never freeze the entire universe.

---

# 13. Retry Classification

Use different behavior for different failures.

## Rate limit

```text
429 / true quota error
        ↓
respect shared limiter/backoff
        ↓
retry once
```

## Network timeout

```text
timeout
   ↓
retry once
   ↓
skip
```

## Empty/invalid response

```text
empty response
   ↓
do NOT automatically classify as quota
   ↓
retry once
   ↓
skip
```

## Invalid symbol

```text
invalid
   ↓
skip immediately
```

Do not waste the second request on a known invalid symbol.

---

# 14. Phase 2.6 — Symbol Timeout

Target:

```text
SYMBOL_TIMEOUT_SEC = 8
```

The existing architecture identifies a much larger timeout as another source of pool stalls.

A symbol that takes too long should not hold the entire harvest hostage.

Expected state:

```text
FETCHING
   ↓
8 sec timeout
   ↓
ERROR / SKIPPED
   ↓
next symbol
```

The exact cancellation mechanism must be compatible with the existing synchronous Fyers SDK and thread pool. Do not assume a Python thread can be forcibly killed.

The important requirement is:

> The harvest must not wait indefinitely for one symbol before processing the rest.

---

# 15. Phase 2.7 — Remove Artificial Batch Sleeps

If the current chain loop has:

```text
BATCH_SLEEP = 0.2
```

or similar artificial delays, remove them from the hot path.

The limiter already controls request pacing.

Do not stack:

```text
limiter wait
+
batch sleep
+
retry sleep
```

unless a specific safety test proves the additional delay is required.

---

# 16. Phase 2.8 — Keep Chain Fetch Lightweight

The chain worker should do:

```text
optionchain
    ↓
store chain
    ↓
CPU signal processing
    ↓
board update
```

It should NOT do:

```text
5m history
3-day option history
futures REST per symbol
MTF REST walk
extra spot REST
```

Those operations belong elsewhere.

---

# 17. Phase 2.9 — Split History Completely Out of scan_all

## File

`option_flow_radar.py`

The chain harvest should finish when:

```text
all chains attempted
+
CPU scoring complete
+
cheap batched futures data available
```

It should NOT wait for:

```text
187 × 15m history
+
187 × D history
```

The original architecture explicitly identifies this as a major delay because history is secondary to the chain listing.

---

# 18. New Harvest Lifecycle

The desired flow is:

```text
HARVEST START
     │
     ▼
Build priority queue
     │
     ▼
Chain pass
     │
     ├── fetch chain
     ├── store chain
     ├── score
     └── publish row
     │
     ▼
Batch futures for scored names
     │
     ▼
FINALIZE CHAIN BOARD
     │
     ▼
HARVEST COMPLETE
```

History does NOT block this lifecycle.

---

# 19. Phase 2.10 — Futures Must Be Batched

Current behavior can fetch futures individually for flagged names.

Do not do:

```text
RELIANCE future → REST
INFY future     → REST
TCS future      → REST
...
```

Instead:

```text
collect future symbols
       ↓
chunks of <=50
       ↓
quotes batch
       ↓
store futures
```

Example:

```text
flagged = 40

get_quotes(
    future_symbols[0:50]
)
```

One request instead of 40.

---

# 20. Phase 2.11 — CPU Analysis Must Be Decoupled from REST Latency

For each successfully fetched chain:

```text
Fyers response
     ↓
normalize
     ↓
store
     ↓
CPU signal engine
     ↓
board
```

Do not make CPU analysis wait for the entire universe.

This means:

```text
RELIANCE fetched
    ↓
RELIANCE analyzed
    ↓
RELIANCE appears
```

while:

```text
INFY
TCS
SBIN
...
```

are still fetching.

---

# 21. Phase 2.12 — Do Not Re-fetch the Chain During Scoring

`_process_option_chain` must receive the already-fetched chain.

Correct:

```python
chain_resp = get_option_chain(...)

result = _process_option_chain(
    ...,
    chain_resp=chain_resp
)
```

Incorrect:

```python
chain_resp = get_option_chain(...)

result = _process_option_chain(...)
# internally fetches chain again
```

This is especially important with four workers because accidental duplicate requests would multiply quota consumption.

---

# 22. Phase 2.13 — Canonical Chain Width

Use one canonical width for stored data:

```text
Equity     = 14
Index      = 20
```

Readers should slice the stored chain.

Do NOT allow every consumer to create a separate Fyers request:

```text
Radar       → 14
Greeks      → 15
Bulk OC     → 20
Home        → 10
VAT         → 20
```

Instead:

```text
Stored chain
     ↓
reader slices locally
```

This avoids systematic cache misses caused by caller-specific widths.

---

# 23. Phase 2.14 — Single-Flight Cache

If multiple requests need the same key at the same time:

```text
Request A ─┐
Request B ─┼── same symbol
Request C ─┘
       ↓
   ONE Fyers call
       ↓
   shared result
```

Implement an in-flight map in `MarketCache.cached_call`.

Concept:

```text
key → Future/Event
```

First caller performs the fetch.

Other callers wait for the same result.

This is especially important for:

```text
NIFTY
BANKNIFTY
FINNIFTY
```

because these symbols are commonly requested by multiple features.

---

# 24. Phase 2.15 — Incremental Board Remains Mandatory

Concurrency must NOT break Phase 1 behavior.

Every completed symbol:

```text
result
 ↓
board upsert
 ↓
publish
```

The board can therefore look like:

```text
Scanned: 41 / 187

A+
  RELIANCE
  INFY

A
  TCS

NO SIGNAL
  SBIN
  HDFCBANK

SKIPPED
  XYZ
```

The user sees useful information immediately.

---

# 25. Phase 2.16 — Board Must Be Deterministic

Concurrent workers can finish in arbitrary order.

Do not let that make the UI unstable.

Store rows by:

```text
symbol
```

Then sort the rendered board by a deterministic ranking:

```text
grade
↓
LIS / desk score
↓
symbol
```

Do not use completion order as the permanent display order.

---

# 26. Phase 2.17 — Harvest Counters

At the end of every chain pass record:

```json
{
  "requested": 187,
  "attempted": 187,
  "ok_chain": 183,
  "hits": 31,
  "no_signal": 152,
  "skipped": 3,
  "errors": 1,
  "elapsed_sec": 68.4,
  "top_tier_elapsed_sec": 11.8,
  "fyers_requests": 187,
  "rate_limit_events": 0,
  "cooldowns": 0
}
```

This is how Phase 2 is judged.

---

# 27. Phase 2.18 — Performance Instrumentation

Track:

```text
queue_wait_ms
limiter_wait_ms
HTTP_latency_ms
processing_ms
publish_ms
total_symbol_ms
```

Example:

```text
RELIANCE
queue       4ms
limiter   330ms
HTTP      912ms
CPU        18ms
publish     3ms
----------------
total    1267ms
```

This tells us where the actual bottleneck is.

---

# 28. Phase 2.19 — Quota Budget

Use this model:

```text
Fyers hard cap:
200 RPM

Operational cap:
180 RPM

Chain:
~3.0 RPS during chain window

Workers:
4

Burst:
<=8 in-flight/request-start safety target
```

Do not allow background work to silently consume the chain budget.

The chain pass owns the critical budget.

---

# 29. Phase 2.20 — History Budget

History is now a background operation.

Example target:

```text
Chain pass:
highest priority

History:
only when chain pass is finished
and budget remains
```

15m history TTL:

```text
~900 seconds
```

Daily history:

```text
once per IST day
```

History should be spread across the available budget rather than delaying the chain board.

---

# 30. Phase 2.21 — Scheduler Cadence

Keep the main full-book cycle around:

```text
180 seconds
```

Do not shorten the entire 187-name harvest cycle to 30 seconds merely because the chain pass becomes faster.

Instead, after the first fast cycle:

```text
0s      harvest
75s     idle / background work
180s    next harvest
```

The exact cadence remains controlled by market/product requirements.

The architecture also considers:

```text
TOP tier every ~90 sec
full book every ~180 sec
```

as a possible future optimization.

Do not introduce that complexity until the basic 180s cycle is proven.

---

# 31. Phase 2.22 — Frontend Polling

Keep:

```text
job poll ≈ 1.5 sec
```

during a running harvest.

Avoid simultaneously running a competing:

```text
/radar/last
```

poll that causes unnecessary duplicate rendering/network activity.

Use one primary clock during a running job.

---

# 32. Phase 2.23 — Row Click Must Be Cheap

After the chain pass:

```text
click symbol
    ↓
read chain from store
    ↓
read stored 15m
    ↓
read idea
    ↓
calculate display-only derived values
```

Expected:

```text
Fyers limiter grants = 0
```

unless an explicit live/debug request is made while the actor is idle.

---

# 33. Phase 2.24 — Failure Behavior

One symbol must never stop the harvest.

Bad:

```text
symbol timeout
 ↓
pool reset
 ↓
whole harvest delayed
```

Good:

```text
symbol timeout
 ↓
record error
 ↓
continue remaining queue
```

The final board must contain the failed symbol's state.

---

# 34. Phase 2.25 — Logging Format

Use structured harvest logs.

Example:

```text
HARVEST_START
pass=h123
requested=187
workers=4
rps=3.0
```

Per symbol:

```text
CHAIN_DONE
pass=h123
symbol=NSE:RELIANCE-EQ
latency_ms=941
grade=A
```

Failure:

```text
CHAIN_SKIP
pass=h123
symbol=NSE:XYZ-EQ
reason=timeout
retry=1
```

Completion:

```text
HARVEST_DONE
pass=h123
attempted=187
ok=184
skipped=2
errors=1
elapsed_ms=69400
rpm_peak=178
cooldowns=0
```

---

# 35. Phase 2 Definition of Done

Phase 2 is complete only when:

- [ ] Four chain workers operate through one shared limiter.
- [ ] Sustained request rate remains within the operational budget.
- [ ] TOP 34 reaches the board within approximately 15 seconds on a clean session.
- [ ] All 187 names are attempted within approximately 75 seconds on a clean session.
- [ ] No six-attempt retry loops remain.
- [ ] Per-symbol timeout is bounded.
- [ ] Artificial batch sleeps are removed.
- [ ] History no longer blocks chain completion.
- [ ] Futures are batched.
- [ ] CPU scoring happens immediately after chain fetch.
- [ ] No chain double-fetch exists.
- [ ] Canonical chain widths are respected.
- [ ] Single-flight prevents duplicate concurrent calls.
- [ ] Partial/incremental board behavior from Phase 1 remains intact.
- [ ] Failed symbols are visible.
- [ ] Quota/cooldown telemetry proves the budget is respected.
- [ ] Performance logs prove the latency target.

---

# 36. Phase 2 Test Plan

## Test 1 — Four-worker concurrency

Mock:

```text
12 symbols
HTTP latency = 1 second
workers = 4
limiter = 0.33 sec
```

Expected:

```text
wall time < 5 seconds
```

Serial execution would be approximately 12 seconds.

---

## Test 2 — 187 chain budget

Mock 187 successful option-chain calls.

Expected:

```text
chain calls <= 187
limiter grants <= ~190
cooldowns = 0
```

Do not accidentally make additional calls during scoring.

---

## Test 3 — TOP tier

Mock slow remaining symbols.

Expected:

```text
TOP 34 complete first
```

and the board starts showing those results before the rest.

---

## Test 4 — Retry

Force one temporary failure.

Expected:

```text
attempt 1
short backoff
attempt 2
success
```

No long cooldown.

---

## Test 5 — Permanent failure

Force a symbol to fail twice.

Expected:

```text
SKIPPED/ERROR
```

and the remaining universe continues.

---

## Test 6 — Timeout

Force one request beyond 8 seconds.

Expected:

```text
symbol marked timeout
remaining queue continues
```

---

## Test 7 — History isolation

Force history requests to be slow.

Expected:

```text
chain board completes without waiting for history
```

---

## Test 8 — Futures batching

For 40 scored symbols:

Expected:

```text
1 quotes batch
```

not:

```text
40 REST requests
```

---

## Test 9 — Row click

After warm harvest:

```text
click 10 rows
```

Expected:

```text
additional optionchain calls = 0
```

---

## Test 10 — Concurrent duplicate request

Trigger multiple requests for the same key simultaneously.

Expected:

```text
Fyers calls = 1
```

---

## Test 11 — Rate budget

Run a full simulated harvest.

Expected:

```text
RPM peak <= 180
429 = 0
cooldown = 0
```

under a clean Fyers mock.

---

# 37. Phase 2 Performance Dashboard

During testing, capture:

```text
┌─────────────────────────────────┐
│ FLOW RADAR HARVEST               │
├─────────────────────────────────┤
│ TOP 34       11.8 sec            │
│ ALL 187      68.4 sec            │
│ Successful   184                 │
│ Skipped        2                 │
│ Errors         1                 │
│                                 │
│ Fyers RPM     178 / 200          │
│ 429             0                │
│ Cooldowns       0                │
│                                 │
│ Workers         4                │
│ Chain RPS     3.0                │
└─────────────────────────────────┘
```

This should be available in logs and ideally `/ready` or a radar diagnostics endpoint.

---

# 38. Phase 2 Files

Primary:

```text
backend/app/services/option_flow_radar.py
backend/app/services/rate_limiter.py
backend/app/services/radar_scheduler.py
backend/app/services/fyers_market.py
backend/app/services/market_cache.py
backend/app/services/levels.py
```

Potentially:

```text
backend/app/core/config.py
backend/app/api/routes/option_flow_radar.py
frontend/.../OptionFlowRadar.tsx
frontend/.../lib/api.ts
```

Do not touch unrelated product logic.

---

# 39. What Phase 2 Must NOT Change

Do NOT rewrite:

```text
radar_signal_engine
idea_engine
idea_book
oi_clusters
execution
desk_decision
mtf_engine
RSI desk scoring
```

unless tests prove an integration bug.

The purpose is:

```text
same analysis
+
faster data
```

not:

```text
new analysis
```

---

# 40. Phase 2 Failure Conditions

Stop Phase 2 and investigate if:

```text
RPM > 180
```

or:

```text
429 appears during clean test
```

or:

```text
TOP 34 gets slower after concurrency
```

or:

```text
same symbol produces multiple OC calls
```

or:

```text
history delays chain completion
```

or:

```text
UI stops showing incremental results
```

Do not compensate by simply increasing the request rate.

---

# 41. Phase 2 Expected Outcome

Before Phase 2:

```text
Correct but slow
```

After Phase 2:

```text
Fast chain collection
+
fast per-symbol analysis
+
incremental board
+
controlled quota
```

The desired user experience becomes:

```text
Click / open Radar
       ↓
TOP names begin appearing
       ↓
analysis appears immediately
       ↓
remaining F&O names continue filling
       ↓
full 187-name board completes
       ↓
history continues independently
```

---

# 42. Phase 3 Handoff

Do not start Phase 3 until Phase 2 has demonstrated:

```text
TOP 34 <= 15 sec
187 <= 75 sec
RPM <= 180
429 = 0
cooldown = 0
```

Phase 3 will then focus on:

```text
Redis persistence
+
WebSocket spots
+
history sweeper
+
store-only application
+
full Market Gateway boundary
+
restart safety
```

---

# 43. Final Phase 2 Principle

The complete rule for Phase 2 is:

> **Parallelize the waiting, not the quota.**

Use multiple workers to hide Fyers network latency.

Use one global limiter to protect the Fyers minute budget.

Fetch each required dataset once.

Store it.

Analyze immediately.

Publish immediately.

Everything else waits for the book.

