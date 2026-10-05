# Flow Radar — Phase 3 README
## Persistent Live Market Book + Store-Only Application

**Project:** `quant_trade-analysis` (OptionGreek)  
**Phase:** 3 of 3  
**Goal:** Turn the fast Phase 2 Radar into a persistent, live, restart-safe, store-driven market system.

---

# 1. Phase 3 Objective

Phase 1 made the system correct.

Phase 2 made the F&O chain harvest fast.

Phase 3 makes the whole application **persistent, live, restart-safe, and store-driven**.

Final principle:

> **Fetch once → store once → analyze many times.**

The final architecture is:

```text
                         FYERS
                    REST + WebSocket
                           │
                           ▼
                  ┌─────────────────┐
                  │  MARKET GATEWAY │
                  │                 │
                  │ rate limiter    │
                  │ quota budget   │
                  │ retries         │
                  │ single-flight   │
                  │ circuit breaker │
                  └────────┬────────┘
                           │
                  ┌────────▼────────┐
                  │   SYMBOL BOOK   │
                  │ Redis + Memory   │
                  │ chain / spot    │
                  │ history / radar │
                  │ derived/futures │
                  └────────┬────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
      Flow Radar       History Sweeper   WS Spot
          │
          ▼
      Signal Engine
          │
          ▼
       Live Board
          │
     ┌────┼────┬────┬────┐
     ▼    ▼    ▼    ▼    ▼
    Home Quant VAT  HV  7/200
          │
          ▼
      STORE ONLY
```

---

# 2. Phase 3 Targets

```text
TOP 34 chains       <= 15 sec
ALL 187 chains      <= 75 sec
Live LTP            < 1 sec target
Warm row click      0 Fyers requests
Normal duplicate OC 0
Normal 429          0
Normal cooldown     0
Operational RPM     <= 180
Restart              previous board survives
```

These are engineering targets; actual Fyers latency can vary.

---

# 3. Preconditions

Do NOT begin Phase 3 until Phase 2 has proven:

- 4-worker chain harvesting works.
- Shared limiter works.
- TOP 34 is fast.
- Full 187 chain pass is fast.
- History does not block chains.
- Futures are batched.
- Duplicate chain fetching is removed.
- Incremental board works.
- Quota telemetry is working.
- Phase 2 tests pass.

---

# 4. Phase 3 Workstreams

Implement in this order:

```text
A. Redis persistence
B. WebSocket live spots
C. History sweeper
D. Store-only readers
E. Market Gateway boundary
F. Final Radar/live-desk UI
```

---

# 5. A — Redis Persistence

## Goal

Radar must retain its latest usable state after:

```text
backend restart
frontend refresh
uvicorn restart
```

The application must not appear empty merely because the process restarted.

## Files

```text
docker-compose.yml
backend/app/core/config.py
.env.example
backend/app/services/redis_client.py
backend/app/services/symbol_store.py
```

## Configuration

```env
REDIS_ENABLED=true
```

Redis becomes the normal development/production contract.

Memory remains a fallback.

## Failure behavior

```text
Redis healthy
    → Redis + memory

Redis unavailable
    → memory fallback
    → /ready = degraded
    → Radar may continue safely
```

Never report persistence as healthy when Redis is down.

---

# 6. Redis Data Model

Use the existing `optiongreek` namespace.

Recommended:

```text
optiongreek:sym:{SYMBOL}
optiongreek:idx:board
optiongreek:meta:harvest
optiongreek:job:{JOB_ID}
optiongreek:idea:{SYMBOL}
```

Keep the established symbol snapshot structure:

```json
{
  "symbol": "NSE:RELIANCE-EQ",
  "name": "RELIANCE",
  "kind": "EQ",
  "harvest_ts": 0,
  "spot": {
    "ltp": 0,
    "change_percent": 0,
    "volume": 0,
    "ts": 0
  },
  "chain": {
    "spot_price": 0,
    "atm_strike": 0,
    "pcr": 0,
    "chain": [],
    "expiries": []
  },
  "history": {
    "15": {"candles": [], "days": 40},
    "D": {"candles": [], "ist_date": ""}
  },
  "futures": {},
  "derived": {
    "vwap": 0,
    "mtf": {},
    "ma7200": {},
    "rel_vol_15": 0
  },
  "radar": {
    "grade": "C",
    "lis": 0,
    "desk_score": 0,
    "hit": false
  }
}
```

Board index remains slim:

```json
{
  "pass_id": "...",
  "phase": "chains",
  "scanned": 40,
  "total": 187,
  "partial": true,
  "flagged": [],
  "watch": [],
  "alert_box": [],
  "errors": [],
  "skipped": [],
  "timestamp": "..."
}
```

Do not duplicate every complete symbol snapshot inside the board.

---

# 7. Redis Restart Test

Test:

```text
1. Run a complete harvest.
2. Confirm /radar/last has data.
3. Kill backend.
4. Restart backend.
5. Request /radar/last.
```

Expected:

```text
previous board immediately available
```

A new harvest may update it, but a full harvest must not be required merely to reconstruct the previous state.

---

# 8. B — WebSocket Live Spots

## Goal

Use Fyers WebSocket for live spot/LTP information.

REST remains responsible for:

```text
option chain
history
quote fallback
```

WebSocket is responsible for:

```text
LTP
change
volume
OHLC/tick data where supported
```

Do NOT attempt to replace full option-chain/OI REST with the WebSocket.

---

# 9. WebSocket Universe

Subscribe the canonical:

```text
ALL_FNO_WATCHLIST
```

Target:

```text
187 underlyings
```

Do not maintain a second WebSocket universe.

The same canonical F&O universe must be used everywhere.

---

# 10. WebSocket → Symbol Book

Flow:

```text
Fyers WS tick
      ↓
normalize
      ↓
symbol_store.put_spot()
      ↓
Redis + memory
```

Each spot record must include:

```text
ltp
change_percent
volume
timestamp
```

The frontend can therefore determine spot freshness.

---

# 11. WebSocket Freshness

Calculate:

```text
spot_age = current_time - spot.ts
```

Classify:

```text
FRESH
STALE
MISSING
```

Do not silently show stale LTP as live.

---

# 12. WebSocket Reconnect

Implement:

```text
CONNECTED
    ↓
DISCONNECTED
    ↓
BACKOFF
    ↓
RECONNECT
    ↓
RESUBSCRIBE 187
    ↓
CONNECTED
```

On reconnect:

1. Re-authenticate if necessary.
2. Restore subscriptions.
3. Mark symbols stale until fresh ticks arrive.
4. Resume `put_spot`.

Do not assume SDK reconnect automatically restores all subscriptions.

---

# 13. REST Spot Fallback

Normal case:

```text
WS healthy
    ↓
no REST spot polling
```

Fallback:

```text
WS disconnected/stale
    ↓
Market Gateway
    ↓
batched REST quotes
```

Never create independent quote polling loops for each page/component.

---

# 14. C — History Sweeper

History must be completely separated from the chain critical path.

Final model:

```text
Radar Harvest
    ├── option chains
    ├── scoring
    └── board

History Sweeper
    ├── 15m history
    └── daily history
```

Both use the same Market Gateway and quota budget.

---

# 15. 15m History

Use the established approximate TTL:

```text
900 seconds
```

When:

```text
history.15 age > TTL
```

queue the symbol.

Do NOT fetch all 187 symbols every Radar cycle.

Use a round-robin queue.

Priority:

```text
1. active/locked ideas
2. A/A+ symbols
3. TOP 34
4. remaining universe
```

History must never block chain harvesting.

---

# 16. Daily History

Track:

```text
history.D.ist_date
```

Fetch once per IST date.

If:

```text
history.D.ist_date == today_IST
```

do not fetch again.

---

# 17. 5m History Policy

Do NOT restore a 5m full-universe walk.

Normal Radar:

```text
NO 5m REST
```

Use stored 15m where the existing product logic permits.

Explicit detail/live requests may use 5m only when:

```text
live=1
+
harvest actor idle
+
gateway budget permits
```

This must remain an explicit exception, not a normal page-refresh behavior.

---

# 18. D — Store-Only Readers

After Phase 3, normal market-data features must not independently walk Fyers.

Store-driven features:

```text
Home
Quant
VAT
7/200
HV
Confluence
Greeks
Sentiment
Flow detail
```

They read:

```text
Symbol Book
```

If the book is not warm:

```text
waiting for harvest
```

is acceptable.

Do not secretly call Fyers.

---

# 19. Store-Only `/market/state`

`GET /market/state`:

```text
read store
    ↓
return stored data
```

If missing:

```json
{
  "success": false,
  "error": "store_miss",
  "harvest_age": 124
}
```

No hidden option-chain request.

---

# 20. Store-Only `/options/chain`

Use canonical stored chain:

```text
stored chain
    ↓
local slice
    ↓
response
```

Example:

```text
stored = canonical 14/20
request = 10
response = local 10-strike slice
```

Never fetch a different width merely because a caller requested another width.

Canonical:

```text
EQ    = 14
INDEX = 20
```

---

# 21. Store-Only Confluence

Remove independent NIFTY option-chain fetching.

Use:

```text
NIFTY symbol snapshot
+
Radar cache
```

This eliminates recurring duplicate NIFTY OC traffic.

---

# 22. Store-Only VAT / HV / 7/200 / Quant

These features consume:

```text
chain
spot
history
derived
radar
```

If unavailable:

```text
waiting for harvest
```

Do not create another universe scan.

This follows the product rule that other pages may be slow/empty while Flow Radar remains the priority.

---

# 23. Trading APIs Stay Separate

Do not break legitimate trading operations.

Keep appropriate direct Fyers/MCP paths for:

```text
orders
positions
funds
profile
orderbook
```

Phase 3 centralizes normal **market-data** access; it does not remove trading functionality.

---

# 24. E — Final Market Gateway Boundary

Phase 1 uses writer isolation.

Phase 3 makes ownership explicit.

Target:

```text
                 Market Gateway
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       quotes        chain       history
          │            │            │
          └────────────┼────────────┘
                       ▼
                     Fyers
```

Normal feature services should not directly access the Fyers market client.

They either:

```text
read Symbol Book
```

or, for the harvest actor:

```text
use Market Gateway
```

---

# 25. Market Gateway Responsibilities

Centralize:

```text
Fyers market-data access
rate limiting
RPM budget
retry policy
timeouts
single-flight
circuit breaker
metrics
cache integration
```

Conceptual API:

```python
gateway.get_chain(symbol)
gateway.get_quotes(symbols)
gateway.get_history(symbol, resolution)
```

But normal readers should already be served by the Symbol Book.

---

# 26. Single-Flight

If an identical request somehow occurs concurrently:

```text
Home ──┐
Quant ─┼── NIFTY
Radar ─┤
      │
      ▼
 ONE request
      │
      ▼
 shared result
```

Implement:

```text
request key → Future/Event
```

First caller performs the request.

Others wait for the same result.

However:

> Single-flight is a safety net. The primary design is still store-only readers.

---

# 27. Circuit Breaker

Use explicit states:

```text
HEALTHY
   ↓
WARNING
   ↓
THROTTLED
   ↓
COOLDOWN
   ↓
RECOVERING
   ↓
HEALTHY
```

Expose:

```json
{
  "fyers": {
    "state": "HEALTHY",
    "rpm_used": 122,
    "rpm_limit": 200,
    "429_count": 0,
    "cooldown": false
  }
}
```

A clean normal session should have:

```text
429 = 0
cooldowns = 0
```

---

# 28. F — Final Live Radar UI

The frontend should feel like a live desk, not a batch job.

Show:

```text
FLOW RADAR

Harvest
42 / 187

Phase
Chains

TOP 34
11.4s

ETA
~63s

Fyers
122 / 200 RPM
HEALTHY
```

---

# 29. Per-Symbol Status

Every valid F&O symbol should have a state.

Example:

```text
RELIANCE    A+       FRESH
INFY        A        FRESH
TCS         —        NO SIGNAL
SBIN        —        SKIPPED
HDFC        —        ERROR
```

This satisfies the complete-universe listing requirement.

A symbol with no trading signal is different from a symbol that failed to fetch.

---

# 30. Freshness Display

Where useful, show:

```text
Chain: 12s
Spot: 0.3s
15m: 84s
```

If stale:

```text
Chain: STALE
```

Never imply stale data is current.

---

# 31. Restart UX

After backend restart:

```text
Redis
  ↓
previous board
  ↓
frontend paints immediately
  ↓
new harvest starts
  ↓
rows update incrementally
```

This is one of the main benefits of Phase 3.

---

# 32. Flow Detail

`GET /radar/flow/{symbol}` should normally read:

```text
stored chain
stored spot
stored 15m
stored derived
stored idea
```

Expected after a warm harvest:

```text
additional Fyers grants = 0
```

Only explicit live/debug behavior may bypass this.

---

# 33. Data Freshness Contract

Do not use one timestamp for everything.

Track separately:

```text
spot       → WS timestamp
chain      → chain harvest timestamp
history15  → history timestamp
historyD   → IST date
futures    → quote timestamp
radar      → scoring timestamp
```

Every UI/API response should be able to distinguish fresh, stale, and missing data.

---

# 34. Canonical Universe Contract

There must be one source for:

```text
FNO_STOCKS       = 184
FNO_INDICES      = 3
ALL_FNO          = 187
TOP_FNO_STOCKS   = 31
```

Every component uses that source.

No duplicate symbol lists.

No different universe for:

```text
Radar
Quant
Greeks
Home
WebSocket
```

---

# 35. Health Endpoints

Keep:

```text
GET /ready
GET /market/store/status
```

Expose:

```json
{
  "radar": {
    "running": false,
    "phase": "idle",
    "scanned": 187,
    "total": 187,
    "last_harvest_age": 18
  },
  "redis": {
    "status": "healthy"
  },
  "websocket": {
    "status": "connected",
    "symbols": 187
  },
  "fyers": {
    "state": "healthy",
    "rpm": 74,
    "429": 0
  }
}
```

---

# 36. Required Operational Alerts

Detect/log:

```text
Redis unavailable
WebSocket disconnected
Fyers 429
Fyers cooldown
harvest over target latency
universe incomplete
stale chain
stale spot
history sweeper lag
```

Do not hide these behind a generic `success=false`.

---

# 37. Phase 3 Test Plan

## Test 1 — Restart persistence

```text
harvest
restart backend
GET /radar/last
```

Expected:

```text
board exists immediately
```

## Test 2 — Redis failure

Turn Redis off.

Expected:

```text
memory fallback works
health = degraded
```

## Test 3 — WebSocket

Connect WS.

Expected:

```text
spot timestamps update
normal REST spot polling = 0
```

## Test 4 — WS disconnect

Expected:

```text
disconnect detected
controlled REST fallback
```

## Test 5 — WS reconnect

Expected:

```text
187 subscriptions restored
spot updates resume
```

## Test 6 — Home

Expected:

```text
store reads
no independent Fyers OC walk
```

## Test 7 — Quant/VAT/HV/7/200

Expected:

```text
store reads
or explicit waiting-for-harvest
```

## Test 8 — Row click

Click 20 rows.

Expected:

```text
unnecessary Fyers OC requests = 0
```

## Test 9 — Duplicate NIFTY consumers

Open/trigger Home + Quant + Confluence + Radar.

Expected:

```text
normal Fyers OC requests = 0
```

after the store is warm.

## Test 10 — Full restart

```text
backend restart
frontend refresh
new harvest
WS reconnect
```

Expected:

```text
old board visible
new board updates incrementally
LTP resumes
```

---

# 38. Phase 3 Definition of Done

- [ ] Redis enabled.
- [ ] Symbol Book survives restart.
- [ ] Last Radar board survives restart.
- [ ] Redis failure is visible as degraded.
- [ ] WebSocket drives live spot data.
- [ ] 187 canonical underlyings are subscribed.
- [ ] WebSocket reconnect/resubscribe works.
- [ ] REST spot fallback is controlled.
- [ ] History is a separate sweeper.
- [ ] 15m history is TTL-driven.
- [ ] Daily history is once per IST date.
- [ ] Full-universe 5m fetching is disabled.
- [ ] Home is store-only.
- [ ] Quant is store-only.
- [ ] VAT/HV/7/200 are store-driven.
- [ ] Confluence no longer independently fetches NIFTY OC.
- [ ] Flow detail is store-first.
- [ ] Market-data Fyers access is centralized.
- [ ] Single-flight is active.
- [ ] Circuit-breaker/health state exists.
- [ ] Freshness timestamps are exposed.
- [ ] Complete-universe state is visible.
- [ ] Restart tests pass.
- [ ] Full integration tests pass.

---

# 39. Final Architecture

```text
                         ┌────────────────────┐
                         │       FYERS        │
                         │                    │
                         │ REST               │
                         │  option chain      │
                         │  history           │
                         │  quote fallback    │
                         │                    │
                         │ WebSocket          │
                         │  LTP / volume      │
                         └─────────┬──────────┘
                                   │
                         ┌─────────▼─────────┐
                         │   MARKET GATEWAY   │
                         │ quota              │
                         │ rate limiter       │
                         │ retry              │
                         │ single-flight      │
                         │ circuit breaker    │
                         │ telemetry          │
                         └─────────┬─────────┘
                                   │
                  ┌────────────────▼────────────────┐
                  │          SYMBOL BOOK             │
                  │          Redis + RAM             │
                  │                                  │
                  │ 187 symbol snapshots             │
                  │ chain / spot / history           │
                  │ futures / derived / radar        │
                  └────────────────┬─────────────────┘
                                   │
                 ┌─────────────────┼──────────────────┐
                 ▼                 ▼                  ▼
             Flow Radar       History Sweeper       WS Spot
                 │
                 ▼
            Signal Engine
                 │
                 ▼
             Live Board
                 │
        ┌────────┼────────┬─────────┬────────┐
        ▼        ▼        ▼         ▼        ▼
       Home    Quant     VAT       HV      7/200
        │        │        │         │        │
        └────────┴────────┴─────────┴────────┘
                         │
                         ▼
                    STORE ONLY
```

---

# 40. Final Three-Phase Result

## Phase 1 — CORRECT

```text
One writer
No quota bleeding
No false cooldown
No duplicate scan
Incremental listing
Correct partial state
```

## Phase 2 — FAST

```text
4 workers
~3 RPS
TOP 34 first
187 <= 75s target
History off hot path
Batched futures
```

## Phase 3 — LIVE + PERSISTENT

```text
Redis
WebSocket
History sweeper
Store-only application
Market Gateway
Restart-safe book
Freshness visibility
```

Final system:

```text
                    Fyers
                      │
                 ONE Gateway
                      │
                      ▼
                    Book
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
      Radar          Home          Quant
        │             │             │
        └─────────────┴─────────────┘
                      │
                  Store only
```

---

# 41. Final Success Criteria

A normal clean session should demonstrate:

```text
TOP 34 visible          <= 15 sec
187 attempted           <= 75 sec
Spot updates            live via WS
History                 non-blocking
Warm row click          store-only
Home                    store-only
Quant                   store-only
VAT                     store-only
HV                      store-only
7/200                   store-only
Confluence              store-only
Redis                   persistent
WS                      connected/recoverable
Fyers                   <= 180 operational RPM
429                     0
Cooldown                0
Duplicate OC            0 normal path
```

The final rule is:

> **Fyers is the market source of truth. The Symbol Book is the application's market database. Radar is the primary harvest/analyze pipeline. Every other feature consumes the book.**
