# Architecture Plan — Flow Radar First, Fyers Budgeted

**Date:** 20 August 2026  
**Repo:** `quant_trade-analysis` (OptionGreek)  
**Status:** Analysis of the live tree + target architecture + implementation spec  
**Product rule (from owner):** other pages may be slow or empty. **Flow Radar must be fully functional, complete F&O listing, and fast.** Quota must not wreck the board.

This file is the working architecture document. It dumps what the code actually does today, why the radar feels lagged / incomplete, and the exact wiring to change.

---

## 0. One-line diagnosis

Flow Radar is slow because **option-chain REST is a scarce resource (Fyers ≈ 10 req/s, 200 req/min)** and this process spends it badly:

1. **Serial harvest** (`ThreadPoolExecutor(max_workers=1)`) so network latency, not the 200/min cap, sets the clock (~0.8–1.5 names/sec instead of ~3).
2. **Quota false-positives + 6 wait-retries per name** (`CHAIN_WAIT_ATTEMPTS=6`, 4–45s sleeps, up to 60–180s cooldown) freeze the walk for minutes on empty JSON bodies.
3. **The UI refuses to list until 100% of 187 names finish** (`/radar/scan/jobs` returns empty `flagged` while running; frontend only `commitScanPayload` on `completed && !partial`).
4. **A process-global `harvest_writer` flag** makes *every* HTTP handler think it is the writer during a scan, so the hidden home dashboard keeps punching Fyers for NIFTY chain / indices while radar is walking the book.
5. **History + futures are bolted onto the same pass** that should only be filling chains, so “scan done” is delayed by a second 15m/D walk of 187 names.

The scoring / CE-PE matrix / idea-lock logic is not the bottleneck. The **I/O schedule and the listing contract** are.

---

## 1. Product constraint (do not dilute)

Owner constraint, restated as engineering law:

| Priority | Rule |
| :--- | :--- |
| P0 | Flow Radar shows **every valid F&O name’s chain result** (hit / skip / error), not a random subset. |
| P0 | First useful board in **≤ 20s** (indices + TOP 31). Full book in **≤ 90s** in a clean session. |
| P0 | Stay under Fyers **200 req/min** and **10 req/s**. Never trip a 60s cooldown on the hot path. |
| P1 | Spots on the board feel live (WebSocket or 15s batched quotes). OI/volume refresh on the harvest cadence. |
| P1 | Other pages (VAT, 7/200, HV, Quant, home widgets) **read the harvest store**. They must not start their own Fyers walks. If they are empty until the first harvest, that is acceptable. |
| P2 | Process-trade lock / grades / LIS stay. Do not rip the signal engine to “make it faster”. |

---

## 2. Current system map

```
Browser (Next.js, one shell: Dashboard.tsx)
  │
  ├─ Home (always mounted, CSS-hidden when you leave)
  │    MarketStateDetector  ──45s──► GET /market/state        ──► optionchain NIFTY
  │    ActiveStrategy       ──45s──► GET /market/state        (same React Query key, 1 fetch)
  │    OptionChainTable     ──45s──► GET /options/chain       ──► optionchain NIFTY again
  │    MarketIndices        ──45s──► GET /market/indices      ──► quotes × 5
  │    ConfluencePanel      ──60s──► GET /confluence          ──► NIFTY OC + radar cache
  │    SystemStatus         ──20s──► /ready, /auth/status
  │
  └─ Flow Radar (kept mounted after first visit)
       GET  /radar/last            (15s auto-refresh)   ── memory/Redis board
       GET  /radar/ideas           (30s)                ── idea book
       POST /radar/scan/start      (manual)             ── full 187 harvest
       GET  /radar/scan/jobs/{id}  (1.5s while running)
       GET  /radar/flow/{symbol}   (row click)          ── OC + 5m history + process attach
       GET  /market/store/status   (15s)

FastAPI (uvicorn, one process)
  lifespan
    Redis init (optional, default OFF)
    candle_aggregator.start()
    RadarScheduler.start()          ── 5s delay, then FULL 187 harvest every 180s while open
    (legacy MA crossover auto-scan DISABLED)

Fyers REST (fyers_apiv3, sync, thread-pooled)
  quotes / history / optionchain / depth / profile / orders
  paced by AsyncRateLimiter.acquire_sync()  min_interval=0.4s  (~2.5 grants/s)

Fyers WebSocket
  implemented (data + order sockets)
  used by candle aggregator if subscribed
  NOT used as the radar’s spot/OI source
```

Stack: FastAPI + Next.js 15 / React 19 / TanStack Query. No DB. Optional Redis (`REDIS_ENABLED` defaults **false**). Fyers is the market source of truth.

---

## 3. Fyers quota (the real budget)

From Fyers API v3 community / docs (unchanged per-second/minute when daily was raised to 1 lakh):

| Window | Cap | What it means for us |
| :--- | ---: | :--- |
| Per second | **10** | Burst ceiling. 8 in-flight is safe; 12 will 429. |
| Per minute | **200** | **The binding constraint.** Sustained ≥ 3.4 RPS will 429 inside a minute. |
| Per day | **100,000** | ~6.25h session × 200/min = 75,000 theoretical. Daily is not the problem. |
| Quotes batch | **50 symbols / request** | One call covers a 50-name chunk. |
| Option chain | **1 underlying / request** | Cannot batch. This **is** the harvest. |
| History | **1 symbol × 1 resolution / request** | Secondary; 15m bar only changes every 15 minutes. |
| Depth | 1 symbol | Not needed for radar listing. |
| WebSocket | up to 5,000 symbols (SDK); our config `ws_max_subscriptions=200` | LTP/OHLC/volume. **Not OI chain.** |

Internal limiter today (`rate_limiter.py`):

```
min_interval = 0.4s     → 2.5 grants/s theoretical = 150/min (under 200)
cooldown_on_limit = 60s, grows to 180s
is_rate_limit_error() matches: request limit, 429, quota, throttle,
  PLUS "expecting value" and "max retries exceeded"
```

**Critical:** `acquire_sync` spaces *grants*, then the HTTP call runs. With `max_workers=1`, effective rate is `1 / (HTTP_latency)` when latency > 0.4s. A 0.8–1.5s optionchain RTT yields **~0.7–1.2 names/sec**, i.e. **~150–270s for 187 chains** before retries, history, or cooldown. That is why a “3 minute harvest” feels like 10–40 minutes.

---

## 4. Universe (exact counts from this tree)

| Set | Count | File |
| :--- | ---: | :--- |
| `FNO_STOCKS` | **184** | `backend/app/services/fno_stocks.py` |
| `FNO_INDICES` | **3** (NIFTY, BANKNIFTY, FINNIFTY) | same |
| `TOP_FNO_STOCKS` | **31** | same |
| `ALL_FNO_WATCHLIST` | **187** after `filter_valid_symbols` | `option_flow_radar.py` |
| Known invalid | TATAMOTORS, NIFTYFIN-INDEX, HDFC | `INVALID_SYMBOLS` |

Scheduler comment still says “TOP-FNO” in the module docstring; the code now harvests **the full 187**. `INTERVAL_OPEN_SECS = 180`.

---

## 5. File-by-file: what exists and how it is wired

### 5.1 Process / config

| File | Role | Wiring issue |
| :--- | :--- | :--- |
| `backend/app/main.py` | FastAPI app, CORS, routers, lifespan. Starts candle aggregator + **RadarScheduler**. Explicitly does **not** start legacy MA crossover. | Scheduler is a second full-book writer alongside any UI `POST /radar/scan/start`. |
| `backend/app/core/config.py` | Fyers creds, WS limits, Redis, harvest TTLs (`harvest_oc_ttl_secs=120`, `harvest_quotes_ttl_secs=15`, `harvest_history_15_ttl_secs=900`, `stale_hard_secs=300`). | `redis_enabled: bool = False`. Harvest store falls back to in-process dicts; restart wipes the book. |
| `docker-compose.yml` | Redis 7 alpine, AOF, 256mb LRU. | Optional. Radar “shared book” is fiction until Redis is on. |
| `dev.bat` / `dev.ps1` | uvicorn + next. | Fine. |

### 5.2 Fyers I/O layer

| File | What it implements | How radar uses it |
| :--- | :--- | :--- |
| `fyers_auth.py` | Session, TOTP auto-login, `FyersModel` singleton, `get_profile` to validate. | Every harvest bails if model is None. |
| `fyers_market.py` | `get_quotes` (≤50), `get_historical_data`, `get_option_chain` (+ Black-Scholes greeks), `get_spot_price`, `get_indices`, `get_market_depth`. Store-first when **not** harvest writer. L1/L2 `MarketCache` TTLs: quotes 15s, OC 90s, history 45s / 15m 900s. | **The only REST door.** Greeks computed locally from chain IV — good, no extra API. |
| `fyers_orders.py` | place/modify/cancel, books, positions, holdings. | MCP trading only. Irrelevant to radar speed. |
| `fyers_websocket.py` | Data socket + order socket. `ws_max_subscriptions=200`. | Candle aggregator subscriber. Radar listing does not consume ticks. |
| `rate_limiter.py` | Process-wide sync+async limiter + cooldown. | Serializes **all** REST including dashboard polls. |
| `market_cache.py` | In-process + optional Redis L2. `cached_call` has **no single-flight**. | Two concurrent NIFTY OC callers both miss → two Fyers hits. |
| `symbol_store.py` | Per-symbol snapshot: spot, chain, history 15/D, derived, futures. `harvest_writer()` context. Reader hit/miss counters. | **Correct idea, broken writer flag (process-global `_harvest_depth`).** |
| `redis_client.py` | Optional JSON get/set, prefix `optiongreek`. | Jobs + last scan + symbol docs. Off by default. |

### 5.3 Flow Radar core (the product)

| File | Logic (keep) vs I/O (change) |
| :--- | :--- |
| `option_flow_radar.py` | **Keep:** CE/PE candidate filter, one-best-strike, grade partition, idea-book attach, harvest quotes pass, derived 7/200 + MTF from stored 15m. **Change:** `scan_all` schedule, retry policy, listing contract, `get_symbol_flow` extra Fyers. |
| `radar_signal_engine.py` | Pure functions. Hard filters: ATM ≤7%, vol spike ≥1.5×, OI Δ ≥8%, min volume 150, greek quality 8/20. LIS, unusual, layers, grades A+/A/B/C. **No I/O. Do not touch for speed.** |
| `radar_scheduler.py` | Background full-book every 180s while market open. Publishes LIS≥65 or HIGH conviction to `signal_bus`. | Must become the **only** harvest trigger. UI must not start a second `scan_all`. |
| `routes/option_flow_radar.py` | REST: last, scan/start, jobs, flow, candles, ideas, levels, backtest. Job poll **strips flagged/ideas until status=completed**. | This is why the tape stays empty/old during a 10-minute walk. |
| `idea_book.py` + `idea_engine.py` | Snapshot ring, hysteresis, lock until invalidation. | CPU only. Keep. |
| `levels.py` | Pivots, Camarilla, CPR, PDH/PDL, VWAP, OR, OI walls. `get_futures` quotes the future **if harvest writer**. After `scan_all`, loops **40 flagged** `get_futures`. | Move futures into a cheap batched quotes pass, not 40 serial calls after the walk. |
| `oi_clusters.py`, `execution.py`, `desk_decision.py` | Cluster magnets, entry/stop/target, HTF gate. | CPU on stored chain. Keep. |
| `mtf_service.py` / `mtf_engine.py` | Daily/4H/1H/15m bias from stored candles. | Keep store-only. |
| `strategies/rsi_desk.py` | `weight_radar_row` stacks LIS + RSI + OC permission + 4H → `desk_score`. Store-only. | Keep. Called twice per scan (per-hit + full re-weight). Harmless CPU. |

### 5.4 Other services that steal Fyers (acceptable to starve)

| File | Fyers it still can fire | Radar impact |
| :--- | :--- | :--- |
| `routes/market_data.py` | spot, state (OC), history, stock scan jobs, HV, bulk OC, live signal, greeks heatmap, nifty sentiment | Home + Quant. Hidden home stays mounted. |
| `routes/option_chain.py` | OC by symbol | Home table, 45s. |
| `confluence.py` | Cached radar + **another NIFTY OC** in intel helper | 60s while home mounted. |
| `nifty_sentiment.py` | VIX spot, **3× NIFTY OC**, quotes of 50 stocks | Quant page. |
| `high_volume_scanner.py` | history per symbol; OC on deep path. Also `scan_from_store` (good). | Radar already rebuilds HV index at end of harvest. |
| `strategies/vat.py` | wide OC + spot + VIX + 15m | VAT page. |
| `strategies/ma7200_scanner.py` | store-first 15m now (good). Analyze still can OC. | |
| `strategies/ma_crossover.py` | history if started | Disabled in lifespan. Keep dead. |
| `tech_filters.py` | 15/60/D history escape hatches | |
| `mcp_service.py` | profile, funds, quotes, OC tools | Agent only. |
| `news_context.py` | Grok, not Fyers | |

### 5.5 Frontend

| File | Behaviour |
| :--- | :--- |
| `app/page.tsx` | Renders `Dashboard` only. No Next routes per feature. |
| `Dashboard.tsx` | View switcher. **Home is `hidden`, not unmounted.** `keepRadar` keeps radar alive after first visit so Back does not wipe the book. Result: home polls **and** radar polls run together. |
| `OptionFlowRadar.tsx` | ~2.4k lines. Tabs: process / flow / tape. Seeds from session cache. `runScan` is **manual** (not on mount — good). Auto-refresh 15s of `/radar/last`. Ideas 30s. Job poll 1.5s. **Will not paint job results unless `completed && scanned >= requested && !partial`.** Row click → `/radar/flow`. |
| `lib/api.ts` | REST wrappers. Radar + market + strategies + MCP. |
| `lib/hooks/useApiQuery.ts` | TanStack Query. `refetchOnWindowFocus: false` (good). |
| `lib/hooks/useMarketData.ts` | Frontend WS to **our** `/ws/market`, not Fyers directly. Underused by radar. |

---

## 6. Flow Radar end-to-end (today)

### 6.1 Happy path

```
Backend start
  sleep 5s
  RadarScheduler.run_once
    radar.scan_all(None, min_lis=0, strike_count=14)
      harvest_writer().__enter__()          # process-global flag ON
      Pass A: get_quotes in chunks of 50    # ~4 calls for 187+indices+VIX
      Pass B: for each of 187 names, SERIAL
        get_option_chain (force on retry)
        score chain, maybe ingest idea (attach_heavy=False → no futures/MTF Fyers)
        on quota-ish error: wait 4–45s, up to 6 times
      Pass C: for each of 187, maybe history 15m (40d) + D (30d) until limiter cooldown
      weight rows, partition A+/A vs B vs alert_box
      persist last_scan (memory + Redis if on)
      get_futures for flagged[:40]
      rebuild HV index from store
      harvest_writer().__exit__()

User opens Radar
  GET /radar/last  → paint last board (or empty)
  15s later same
  User clicks Scan
    POST /radar/scan/start
      if scheduler already running → job_id null, UI polls /radar/last every 2s
      else create scan_job, asyncio.to_thread(scan_all)   # SECOND full walk
    poll GET /radar/scan/jobs/{id} every 1.5s
      running → flagged=[] ideas=[]   # progress bar only
      completed && !partial → replace board
      completed && partial → KEEP previous board, show error
                    “Scan finished before every FNO name was fetched”
```

### 6.2 What one name costs on the scan path (current `scan_all`)

Designed hot path (`_scan_one`, `fetch_vol_history=False`, `attach_heavy=False`):

| Step | API | Notes |
| :--- | :--- | :--- |
| Quotes pass (once per 50) | `quotes` | Shared. ~0.02 calls/name amortized. |
| Option chain | `optionchain` strikecount 14 (indices 20 canonical) | **1 call. Mandatory.** |
| 3-day option volume | skipped | Good. Chain-relative spike used. |
| 5m history / futures / MTF Fyers | skipped on harvest | Good. |

Then after the whole book:

| Step | API | Notes |
| :--- | :--- | :--- |
| History 15m if stale | `history` res=15 days=40 | 1/name, TTL 900s so ~once per 15 min |
| History D if stale | `history` res=D days=30 | 1/name, once per IST day if stamp works |
| Futures for top 40 hits | `quotes` 1 future each | 40 serial |

**Clean first open of the day:**  
`4 quotes + 187 OC + 187 hist15 + 187 histD + 40 fut ≈ 605 REST calls.`  
At a true 3 RPS that is ~3.4 minutes.  
At the actual serial ~1 RPS plus retries, **10–40 minutes**, and the UI shows nothing new until the end — or keeps the old board and says the scan was partial.

### 6.3 Click-into-row (`get_symbol_flow`) — extra Fyers on the interactive path

```
_get_underlying_data(light=False)  → spot + history 5m/1d
get_option_chain
_process_option_chain              → may attach_heavy (futures, 5m enrich)
```

A single row click can cost 2–4 REST calls **during** a harvest, stealing tokens from the walk.

### 6.4 Listing contract (why “no proper fetching and listing”)

Three independent policies all hide rows:

1. **Job API** (`routes/option_flow_radar.py` ~408–413): while `status != completed`, `flagged`, `watch`, `alert_box`, `ideas` are forced to `[]`. Progress log of last 28 names only.
2. **Frontend** (`OptionFlowRadar.tsx` ~1648–1658): even on `completed`, payload is dropped if `partial` or `scanned < requested`.
3. **`scan_all` last_scan write** (~1205–1213): a partial pass is not allowed to replace `_last_scan` if a full one already exists. Combined with (1), the user sees a frozen previous board or an empty first visit.

So the engine **has** per-name hits in `all_hits` in memory; the wire protocol **throws them away** until a perfect 187/187 finish. Quota skips make `partial=True`, which makes a finished scan look like a failure.

That is the “awkward analysis / no proper listing” bug, independent of speed.

---

## 7. Root-cause list (ranked)

### R1 — Serial optionchain cannot hit the minute budget

`max_workers=1` + limiter grants 0.4s apart + HTTP 0.8–1.5s ⇒ **effective 0.7–1.2 RPS**.  
Fyers allows **200/min ≈ 3.3 RPS**. We leave ~2 RPS on the table and still feel rate-limited because the walk is long enough for other callers to collide.

**Fix:** 3–4 concurrent chain fetches, limiter at **0.33s** (≈3.0 RPS, 180/min). Hide RTT. Full OC book in **~60–70s**.

### R2 — False 429s trip 60–180s cooldowns

`is_rate_limit_error` treats JSON `"Expecting value"` (empty gateway body) and `"max retries exceeded"` as quota. Harvest then:

- `trip_limit` 60s+
- `_fetch_chain_wait` up to 6 attempts × 4–45s
- `_quota_err` treats any `no_chain:*` as quota

One flaky name parks the entire 187-walk.

**Fix:** Only trip on real 429 / “request limit”. Skip the name, retry next pass. Cap per-name wait at **one** short backoff (e.g. 1.5s), then move on.

### R3 — UI listing waits for perfection

Job hides rows; frontend rejects partials.

**Fix:** Stream a **live board**. Every name completion upserts that symbol into `last_scan` + job snapshot. Frontend paints running results. Partial is normal, not an error.

### R4 — `harvest_writer` is process-global

```python
# symbol_store.py
_harvest_depth = 0          # not thread-local
def is_harvest_writer():
    return _harvest_depth > 0
```

While `scan_all` holds the context, **dashboard / confluence / flow-click / MCP** all skip the reader path and call Fyers. They share the same limiter → harvest stalls → more “quota”.

**Fix:** thread-local (or explicit `writer_token` passed into `fyers_market`). Default for all HTTP routes: **store only, no escape hatch**, except a single `force=1` debug query.

### R5 — Hidden home dashboard keeps polling

`Dashboard.tsx` hides home with CSS. Those React Query intervals stay alive:

| Widget | Interval | Fyers if store miss / writer flag on |
| :--- | ---: | :--- |
| Market state | 45s | NIFTY optionchain |
| Option chain table | 45s | NIFTY optionchain (second key) |
| Indices | 45s | quotes |
| Confluence | 60s | NIFTY optionchain again |

Owner said other pages may die. **Unmount home, or pause queries when `currentView !== 'dashboard'`, or make those routes store-only.**

### R6 — Two full harvests (scheduler + UI Scan)

`RadarScheduler` every 180s **and** `POST /radar/scan/start` both call `scan_all` on 187 names. The start route tries to reuse a running job, but scheduler does not register a `scan_jobs` job — UI then gets `job_id: null` / “blocked” and waits on `/radar/last`. Confusing listing, duplicate work if timings miss.

**Fix:** Scheduler **is** the harvest. UI Scan = “nudge if idle”, never a second universe walk. One `scan_all` in the process.

### R7 — History pass blocks “done”

Pass C walks 187 × up to 2 history calls after chains. First session this doubles the Fyers count and delays `completed`. 15m bars do not belong on the listing critical path.

**Fix:** Chain pass publishes the board and marks job `completed` (or `chains_done`). History is a **background sweeper** every 15 minutes, budgeted leftover RPS.

### R8 — Redis off by default

In-memory store dies on reload. Frontend session cache is the only persistence. After restart, first visit is empty until a full harvest finishes — which, with R1–R7, is a long time.

**Fix:** `REDIS_ENABLED=true` in local/prod contract. Symbol snapshots + last_scan + idea book survive.

### R9 — `cached_call` thundering herd

No in-flight lock. Concurrent `/market/state` + `/options/chain` + harvest retry for NIFTY = 3 identical optionchain REST calls.

**Fix:** single-flight map `key → Future`.

### R10 — Quotes REST for something WebSocket already does

Spots change every tick; chains (OI) do not. We spend quotes REST and still show stale LTP on the board until the next 180s pass.

**Fix:** Fyers data socket subscribed to the 187 underlyings (under the 200 cap). Write LTP into `symbol_store.spot`. Radar rows read spot from store. **Do not** try to get OI from WS — Fyers does not give a full chain on the data socket.

### R11 — Depth unused; MCP/orders out of band

`get_market_depth` is unpaced (does not even use `_invoke`). Leave it unused. Orders stay on MCP.

### R12 — `get_symbol_flow` double optionchain

`get_symbol_flow` (`option_flow_radar.py` ~1270) fetches the chain, then calls `_process_option_chain` **without** `chain_resp=` (~1343), which fetches again. Usually L1 hits; during harvest (writer flag on) it is **two REST calls per row click**. Pass `chain_resp` through. One line.

### R13 — 5m history is not in the book

Harvest stores **15m + D only**. Flow click, VAT, backtest, `/radar/levels` request **resolution=5**. Store miss → Fyers every time (L1 TTL 900s if someone else just fetched it). Either stop asking for 5m (use stored 15m) or harvest 5m for TOP 34 only.

### R14 — Width / universe mismatches force extra OC and quotes

| Caller | Width / names | Harvest has | Result |
| :--- | :--- | :--- | :--- |
| Greeks heatmap | `strike_count=15` | equity 14 | systematic store miss → Fyers |
| Bulk OC | 20 | equity 14 | same |
| Home OptionChainTable | default 10 | 14/20 | OK if store warm (slice) |
| `get_indices` | NIFTY, BANKNIFTY, FINNIFTY, **NIFTYIT**, **SENSEX** | harvest quotes = FNO + VIX, **no NIFTYIT/SENSEX** | 45s home poll always REST for those two |

Canonical width everywhere. Harvest quotes pass must include whatever home/radar shows.

### R15 — Scheduler is invisible to ScanJob; 90s lock steal

`RadarScheduler.run_once` does **not** create a `scan_jobs` job. UI Scan during a scheduler pass gets `job_id: null` / blocked, or after **90s** idle heartbeat `_scan_running` is stolen (`option_flow_radar.py` 819–829) and two walks interleave store writes. Register the scheduler pass as the radar job. Steal only if heartbeat is dead **and** no job is `running`.

### R16 — Harvest-path scoring is intentionally starved

Pass B sets `vwap=ltp` and a fake EMA (`_underlying_from_store`). `fetch_vol_history=False`. `attach_heavy=False` so no futures until the end. LIS VWAP/EMA layers are noise until Pass C 15m lands — which currently **blocks** “scan done”. After history is split (R7), derived VWAP from **already stored** 15m must be applied on the same name before upsert, not in a later pass the UI never waits for.

Also: `errors` still increment `scanned`, so `partial = scanned < total` is almost never true. A 40%-failed walk still **replaces** `_last_scan` and the frontend thinks it is complete. Count `ok_chain` separately from `attempted`.

---

## 8. Quota math for the target design

Session ≈ 9:15–15:30 IST = 375 minutes. Minute cap 200 ⇒ **75,000** theoretical. We will use far less.

### 8.1 Bind a hard budget (token bucket)

```
FYERS_RPS_BURST     = 8          # never above 10
FYERS_RPM           = 180        # leave 20/min headroom vs 200
CHAIN_RPS           = 3.0        # 180/min dedicated during chain pass
QUOTE_BATCH         = 50
UNIVERSE            = 187
TOP_TIER            = 31 + 3 indices = 34
```

### 8.2 Per 3-minute cycle (steady state)

| Work | Calls | When |
| :--- | ---: | :--- |
| Batched spots (REST fallback if WS down) | 4 | t=0, only if WS stale |
| Option chain **tier 0** (34 names) | 34 | t=0–12s |
| Option chain **tier 1** (remaining 153) | 153 | t=12–65s |
| History 15m stale only (~187/ (900/180) ≈ 37/cycle) | ~40 | t=65–80s, leftover RPM |
| History D (once per name per day) | 0 after first cycle | pre-open or first cycle |
| Futures quotes batched (flagged ∪ locked ideas, ≤50) | 1 | end of chain pass |
| **Total / 180s** | **~230** | **≈ 77/min average, peak 180/min during chain window** |

First open of day (cold history): +187 15m +187 D = +374. Do **pre-open warmup** 8:50–9:14 using leftover daily cap, or stretch history across the first 15 minutes **after** the board is live.

### 8.3 Latency target

| Milestone | Target | How |
| :--- | ---: | :--- |
| Indices + TOP 31 on screen | **≤ 15s** after harvest start | Priority queue; incremental publish |
| Full 187 chains attempted | **≤ 75s** | 3 RPS × 4 workers hiding RTT |
| History warm | **≤ 15 min**, non-blocking | Sweeper |
| Row click chain | **0 Fyers** if age < 120s | Store read |
| Spot flicker | **< 1s** | WebSocket |

---

## 9. Target architecture

```
                    ┌─────────────────────────────────────┐
                    │           Fyers                      │
                    │  REST: optionchain, history (rare)   │
                    │  WS:   LTP/OHLC/vol for 187 names    │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │     Market Gateway (ONE writer)      │
                    │  fyers_market + rate_limiter         │
                    │  thread-local writer OR dedicated    │
                    │  harvest actor                       │
                    │  single-flight + paced 180 RPM       │
                    └──────────────┬──────────────────────┘
                                   │ write
                    ┌──────────────▼──────────────────────┐
                    │     Symbol Book (Redis + memory)     │
                    │  optiongreek:sym:{SYMBOL}            │
                    │    spot, chain, history.15, history.D│
                    │    derived (vwap, mtf, ma7200, rsi)  │
                    │    futures, harvest_ts               │
                    │  optiongreek:idx:board  (live radar) │
                    │  optiongreek:meta:harvest            │
                    └──────────────┬──────────────────────┘
                                   │ read only
          ┌──────────────┬─────────┼──────────┬────────────┐
          ▼              ▼         ▼          ▼            ▼
     Flow Radar      Home*      VAT*      7/200*        HV*
     (product)      store-only  store     store         store
                                *may be empty; no Fyers
```

### 9.1 Components

**A. Harvest actor (replace today’s mixed scheduler + UI job + scan_all I/O)**

One asyncio task, market hours only:

1. **Quotes/WS reconcile** (if WS not connected: 4 REST batches).
2. **Chain pass** with priority:
   - locked ideas
   - previous A/A+ hits
   - indices
   - TOP 31
   - rest of 187, previously-failed first
3. For each name: REST optionchain → store.put_chain → **CPU score** (`_process_option_chain` with stored chain, no extra Fyers) → upsert board row.
4. Batched futures quotes for names that scored.
5. Publish `idx:board` after every name (or every 5 names to cut Redis chatter).
6. Sleep until 180s wall, or immediately if nudge.

**B. History sweeper (separate task)**

Round-robin 15m when `age > 900s`. D once per IST date. Never holds the chain lock. Shares the same limiter so RPM stays ≤180.

**C. Spot socket**

On auth: subscribe 187 underlyings `SymbolUpdate`. On tick: patch `spot.ltp/chp/volume` in store. Radar UI 15s poll already re-reads `/radar/last`; optionally patch LTP client-side via existing `/ws/market` later.

**D. Reader API**

| Route | After cutover |
| :--- | :--- |
| `GET /radar/last` | board + harvest meta. Always. |
| `GET /radar/scan/jobs/{id}` | **includes live flagged/watch/alert_box**. |
| `POST /radar/scan/start` | nudge actor; return current job/pass id. |
| `GET /radar/flow/{symbol}` | store chain + store 15m as 5m-proxy + idea. Fyers only if `stale_hard` and actor idle. |
| `GET /market/state`, `/options/chain`, confluence, VAT, 7/200, HV | **store only**. 404/empty with `harvest.age` if missing. |
| `GET /market/store/status` | keep — this is the health of the book. |

**E. Frontend listing**

- On mount: `/radar/last` (unchanged).
- While harvest.running: poll `/radar/last` or job every 1.5s and **paint whatever flagged/watch exists**.
- Per-name status strip: `scanned/total`, current symbol, last error, skipped count.
- Do **not** require `!partial`.
- Do **not** start a competing scan on auto-refresh (already true).
- Unmount or `enabled: currentView==='dashboard'` for home queries.

### 9.2 Data contract (symbol snapshot)

Keep `symbol_store.empty_snapshot` shape. Canonical chain width: **14 equity / 20 index**, never key by caller `strike_count`. Readers slice.

```json
{
  "symbol": "NSE:RELIANCE-EQ",
  "name": "RELIANCE",
  "kind": "EQ",
  "harvest_ts": 1690000000.0,
  "spot": { "ltp": 0, "change_percent": 0, "volume": 0, "ts": 0 },
  "chain": { "spot_price": 0, "atm_strike": 0, "pcr": 0, "chain": [], "expiries": [] },
  "history": { "15": { "candles": [], "days": 40 }, "D": { "candles": [], "ist_date": "2026-08-20" } },
  "futures": {},
  "derived": { "vwap": 0, "mtf": {}, "ma7200": {}, "rel_vol_15": 0 },
  "radar": { "grade": "A", "lis": 72, "desk_score": 81, "hit": true }
}
```

Board index `optiongreek:idx:board`:

```json
{
  "pass_id": "h...",
  "phase": "chains|history|idle",
  "scanned": 40,
  "total": 187,
  "partial": true,
  "flagged": [ /* A/A+ rows */ ],
  "watch": [],
  "alert_box": [],
  "ideas": [],
  "errors": [],
  "skipped": [],
  "timestamp": "..."
}
```

`partial=true` while `scanned < total` is **expected** and displayable.

### 9.3 What we stop fetching on the radar hot path (already partly done — finish it)

| Call | Today | Target |
| :--- | :--- | :--- |
| Per-name `get_spot_price` | fallback if store empty | WS or quotes pass only |
| Option 3-day history | off on harvest, on in detail | stay off |
| 5m history per name | off on harvest, on in `get_symbol_flow` | derive session VWAP from stored 15m |
| MTF Fyers walk | skipped | stored 15m→60/240 |
| Futures per flagged serial | 40 quotes after pass | **one** batched quotes of future symbols |
| `force_chain=True` retries | wipes cache, re-hits | never force unless age > OC TTL |

---

## 10. Implementation spec (concrete)

Work is ordered so Radar becomes usable after PR-1, fast after PR-2, complete after PR-3. Other pages are not in the critical path.

### PR-1 — Stop the bleeding (half day)

**Goal:** one writer, no false cooldowns, home cannot steal tokens, UI can list a partial board.

1. **`rate_limiter.is_rate_limit_error`**
   - Remove `"expecting value"` and `"max retries exceeded"`.
   - Match only: `429`, `request limit`, `rate limit`, `too many requests`, `quota exceeded`.
2. **`symbol_store.harvest_writer`**
   - Use `threading.local().depth` (or a dedicated harvest thread id). HTTP worker threads are never the writer.
3. **Reader hard mode** (config `fyers_reader_escape=false` default)
   - `get_quotes` / `get_option_chain` / `get_historical_data`: if not writer and store miss → return stored stale **or** `{success:false, error:"store_miss"}`. No Fyers.
4. **Dashboard**
   - `enabled: currentView === 'dashboard'` on home `useApiQuery`, **or** unmount home when leaving.
   - Radar: `commitScanPayload` on job snapshots even when `status==='running'` if `flagged.length>0`.
5. **Job route**
   - While running, return `flagged/watch/alert_box` from `job.results` **and** from `service.get_last_scan()` merged by symbol.
6. **`scan_all` progress**
   - After each name, upsert that symbol into `_last_scan` lists (replace previous row for that symbol) and persist a slim board. Do not wait for 187.
7. **Scan start**
   - Scheduler `run_once` **creates/reuses** the radar `ScanJob` so the UI progress bar is the real harvest.
   - If scheduler is already in `scan_all`, UI Scan is a nudge only — never `asyncio.to_thread(scan_all)` again.
   - Remove 90s lock-steal unless the job is `interrupted` / heartbeat dead **and** no running job exists.
8. **`get_symbol_flow`**
   - Pass existing `chain_resp` into `_process_option_chain` (kill the double OC).

**Files:** `rate_limiter.py`, `symbol_store.py`, `fyers_market.py`, `option_flow_radar.py`, `routes/option_flow_radar.py`, `radar_scheduler.py`, `Dashboard.tsx`, `OptionFlowRadar.tsx`, `config.py`.

**Done when:** clicking Scan no longer 429-spirals; rows appear as names finish; leaving Radar for Home does not start extra NIFTY OC.

### PR-2 — Fast chain harvest (one day)

**Goal:** 187 option chains in ≤75s, TOP 34 in ≤15s.

1. Replace `ThreadPoolExecutor(max_workers=1)` with **4 workers** sharing `acquire_sync`.
2. Limiter `min_interval=0.33` (≈3.0 RPS). Optional harvest-only profile; restore 0.4 when idle.
3. Priority deque as in §9.1.
4. Retry: **once**, 1.5s sleep, then `skipped+=1`, next name. Never `CHAIN_WAIT_ATTEMPTS=6`. Never `force_refresh` on retry unless TTL expired.
5. Drop `BATCH_SLEEP=0.2` extra sleeps (limiter is enough).
6. `SYMBOL_TIMEOUT_SEC`: 8s, not 25s. On timeout, skip (do not reset the whole pool unless the future is actually stuck).
7. Split **history out of `scan_all`**. `scan_all` ends after chains + batched futures + CPU derived from whatever 15m is already stored.
8. Scheduler interval stays 180s; chain pass itself should finish well inside that.

**Files:** `option_flow_radar.py`, `rate_limiter.py`, `radar_scheduler.py`.

**Done when:** logs show `scanned=187` in <80s on a clean token; TOP names hit the board in the first 15s.

### PR-3 — Book + Redis + WS spots (one day)

**Goal:** restart-safe book; live LTP; row click is free.

1. Document + `.env.example`: `REDIS_ENABLED=true`. Fail health `degraded` if Redis configured but down (still run, memory fallback).
2. Start Fyers data socket on auth; subscribe `ALL_FNO_WATCHLIST` (187 < 200 cap). Tick → `store.put_spot`.
3. Quotes REST pass only if WS disconnected or >15s since last tick for that name.
4. `get_symbol_flow`: read store chain + store history 15 (map to candles) + idea. Pass `chain_resp` through. No 5m Fyers unless user passes `live=1` and actor idle. VAT / backtest / levels use 15m too.
5. History sweeper task in lifespan, RPM leftover.
6. Futures: collect future symbols for scored names, `get_quotes` in ≤50 batches, `put_futures`.

**Files:** `fyers_websocket.py`, `main.py`, `option_flow_radar.py`, `levels.py`, `.env.example`.

**Done when:** after one harvest, killing uvicorn and restarting still paints `/radar/last`; LTP moves without a new OC; clicking a row does not move the limiter.

### PR-4 — Frontend as a live desk (half day)

1. Live table: merge incoming rows by `symbol` (one row per name). Show `grade`/`skip`/`err`.
2. Progress: `scanned/total`, ETA from rolling ms/name, cooldown badge from `/ready` limiter.
3. Remove “Previous board kept” error for partial — show skipped list instead, with Retry-skipped (nudge actor to prioritize those).
4. Stop 15s `/radar/last` from fighting the 1.5s job poll (one clock).
5. Optional: subscribe frontend `/ws/market` for selected row LTP.

**Files:** `OptionFlowRadar.tsx`, `lib/api.ts`, `routes/health.py` (limiter stats already exist).

### PR-5 — Starve other pages (optional, owner-approved)

Make store-only and skip Fyers:

- `GET /market/state`, `/options/chain`, `/market/nifty-sentiment`, `/market/live-trade-signal`, VAT scan, HV start, stocks scan start, confluence NIFTY OC.

Leave MCP orders/profile. Leave auth.

This is how Quant/VAT/7/200 stay “wired” without stealing the radar budget. They compute from the same 187 snapshots.

---

## 11. Implementation notes (code-level)

### 11.1 Thread-local writer

```python
# symbol_store.py
_tls = threading.local()

@contextmanager
def harvest_writer():
    d = getattr(_tls, "depth", 0)
    _tls.depth = d + 1
    try:
        yield
    finally:
        _tls.depth = getattr(_tls, "depth", 1) - 1

def is_harvest_writer() -> bool:
    return getattr(_tls, "depth", 0) > 0
```

`scan_all` already runs in `asyncio.to_thread`; the harvest thread is the only writer. FastAPI threadpool handlers stay readers.

### 11.2 Single-flight

In `MarketCache.cached_call`, under the lock, if key in `_inflight`, wait on that event. One Fyers call per key.

### 11.3 Incremental board upsert

```python
def _upsert_board(self, hit, symbol, err):
    board = self._last_scan or empty_board()
    if hit:
        # replace same symbol in flagged/watch/all_hits
        ...
    board["scanned"] += 1
    board["partial"] = board["scanned"] < board["universe_requested"]
    board["timestamp"] = datetime.now().isoformat()
    self._last_scan = board
    self._last_scan_at = datetime.now()
    self._persist_last_scan()
```

Job `mgr.update(results=board["flagged"])` every name (or every 5).

### 11.4 Concurrent chain fetch

```python
with ThreadPoolExecutor(max_workers=4) as pool:
    for hit, err in pool.map(_scan_one, priority_watch):
        _upsert_board(...)
```

`_scan_one` already calls `get_option_chain` → `_invoke` → `acquire_sync`, so 4 threads still cannot exceed the limiter. They only overlap HTTP RTT.

### 11.5 Do not raise RPS above 3.3 sustained

A tempting “set min_interval=0.1 (10 RPS)” will 429 at second 21 (`10×21=210 > 200/min`). Concurrent workers **without** a lower interval is the correct speed-up.

### 11.6 Pre-open warmup (optional PR-3.1)

08:50–09:14 IST: history 15m+D for 187 at 3 RPS ≈ 2 minutes. Chains can wait until 09:15 when OI starts moving. Board at 09:15:15 has TOP 34 live OI.

### 11.7 Kill the flow-click double fetch

```python
# option_flow_radar.get_symbol_flow
chain_resp = self.market_service.get_option_chain(symbol, strike_count)
best = self._process_option_chain(
    symbol, underlying, strike_count, chain_resp=chain_resp
)
```

Never call `_process_option_chain` without `chain_resp` when you already have it.

### 11.8 Canonical width + harvest quote universe

- One `strike_count` for the book: 14 equity / 20 index. Heatmap/VAT/bulk **slice**, never request 15 or 20 on an equity.
- Quotes pass includes `get_indices()` names (NIFTYIT, SENSEX) or home indices route becomes store-only on the three harvested indices.

### 11.9 Completeness counters

```python
attempted += 1          # walked this name
ok_chain += 1           # Fyers OC success
hits += 1               # scored row
skipped.append(sym)     # quota/timeout/invalid
partial = ok_chain < total
```

Frontend lists **all three**: hits, skips, errors. `scanned == total` is not “data is good”.

---

## 12. Logic we keep (do not rewrite)

These are the “many logics” the owner mentioned. They are fine. The wiring around them is not.

| Logic | File | Why keep |
| :--- | :--- | :--- |
| CE/PE × OI × premium matrix | `radar_signal_engine.classify_signal` | Correct institutional labels |
| LIS v2 + greek quality + unusual + grades | `radar_signal_engine` | Product |
| One best strike per name + opposing flag | `option_flow_radar._process_option_chain` | Board unit |
| Idea lock / hysteresis / invalidation | `idea_engine`, `idea_book` | Stops 10s flip (see `docs/flow.md`) |
| OI clusters → entry/stop/target | `oi_clusters`, `execution` | Process trade |
| MTF gate Daily/4H/1H | `mtf_engine` | Direction permission |
| Desk score (RSI + OC permission + 4H) | `rsi_desk.weight_radar_row` | Ranking |
| Chain-relative vol spike (no 3d hist) | harvest path | Saves 2 Fyers/name |
| Canonical chain width 14/20, cache key without strike_count | `fyers_market.get_option_chain` | Already fixed vs old routingfix.md |

`docs/routingfix.md` (14 Aug) described the harvest-store idea. Large parts landed (`symbol_store`, store-first, harvest in `scan_all`, MA7200 store-first, HV `scan_from_store`). **What did not land:** thread-local writer, incremental listing, concurrent chains, history split, Redis-on, WS spots, home unmount. This plan finishes that architecture instead of inventing a third one.

---

## 13. File-level Fyers call inventory (complete)

### REST used

| Fyers method | Wrapper | Callers (market data) |
| :--- | :--- | :--- |
| `fyers.quotes` | `FyersMarketService.get_quotes` | radar harvest chunks; `get_spot_price`; `get_indices`; `levels.get_futures`; nifty breadth; VAT VIX; MCP tool |
| `fyers.history` | `get_historical_data` | radar 5m (detail), 3d vol (detail), harvest 15/D; levels day map (writer); HV; VAT; tech_filters; ma_crossover (disabled); backtest |
| `fyers.optionchain` | `_get_option_chain_uncached` | radar scan; `get_symbol_flow`; `/options/chain`; `/market/state`; confluence nifty; nifty_sentiment ×3; VAT; stocks scan; live signal; greeks heatmap; MCP |
| `fyers.depth` | `get_market_depth` | unused by radar; **not rate-limited** |
| `fyers.get_profile` | auth validate | `/auth/status`, MCP |
| `fyers.funds/positions/orderbook/...` | `fyers_orders.py` + MCP | trading |
| `fyers.place_order` etc. | orders | MCP, kill-switched unless `mcp_trading_enabled` |

### WebSocket used

| Socket | Status |
| :--- | :--- |
| Data `SymbolUpdate` | Implemented; aggregator subscriber; **not driving radar spots** |
| Data `DepthUpdate` | Implemented; unused |
| Order socket | Implemented; unused by radar |

---

## 14. Frontend poll inventory (what fights the harvest)

| Component | Interval | Mounted when | Fyers? |
| :--- | ---: | :--- | :--- |
| OptionFlowRadar last+store | 15s | after first Radar visit (`keepRadar`) | no (reads) |
| OptionFlowRadar ideas | 30s | same | no |
| OptionFlowRadar job | 1.5s | during scan | no |
| MarketStateDetector | 45s | **home always mounted** | OC NIFTY |
| ActiveStrategy | 45s | home | same query key as state |
| OptionChainTable | 45s | home | OC NIFTY |
| MarketIndices | 45s | home | quotes |
| ConfluencePanel | 60s | home | OC NIFTY + cache |
| SystemStatus | 20s | home footer | no |
| VATScanner | 45s | VAT view | OC |
| MA7200 / HV / Stocks | 1.5s job poll | those views | their own walks if started |
| Greeks/Live/Sentiment | 30s | Quant | OC / quotes |
| alerts-hub | 30s | hub | no |

**Highest-leverage frontend change:** stop home queries while Radar is the active product.

---

## 15. Key decisions

| Decision | Choice | Why |
| :--- | :--- | :--- |
| Product | Flow Radar is the only Fyers market writer | Owner: other pages optional |
| Scarce resource | Optionchain REST, budgeted 180/min | Fyers 200/min cap |
| Speed lever | Concurrency to hide RTT, **not** higher RPS | 10 RPS blows the minute cap |
| Listing | Incremental, partial is valid | Waiting for 187/187 is why the UI looks broken |
| Spots | WebSocket | Quotes REST is wasted on LTP |
| History | Separate sweeper | 15m bar ≠ option flow |
| Writer flag | Thread-local | Global flag poisons readers |
| Escape hatch | Off | Readers must not stampede |
| Redis | On | Book must survive restart |
| Signal logic | Keep v3/v4/v5 scoring | Not the lag source |
| Scheduler vs UI | One actor, UI nudges | Two `scan_all` is duplicate quota |
| Other pages | Store-only | Accept empty until harvest |

---

## 16. PR plan (ordered)

| PR | Title | Files | Depends | Outcome |
| ---: | :--- | :--- | :--- | :--- |
| 1 | Stop quota bleed + list partial boards | `rate_limiter.py`, `symbol_store.py`, `fyers_market.py`, `option_flow_radar.py`, `routes/option_flow_radar.py`, `radar_scheduler.py`, `Dashboard.tsx`, `OptionFlowRadar.tsx`, `config.py` | — | No false 429 spirals; rows stream; home does not steal OC |
| 2 | Concurrent chain harvest + split history | `option_flow_radar.py`, `rate_limiter.py` | PR-1 | Full F&O chains ≤75s; TOP 34 ≤15s |
| 3 | Redis-on + WS spots + store-only flow click | `main.py`, `fyers_websocket.py`, `option_flow_radar.py`, `levels.py`, `.env.example` | PR-2 | Live LTP; restart-safe book; click is free |
| 4 | Radar UI live desk | `OptionFlowRadar.tsx`, `api.ts` | PR-1 | Proper fetching + listing UX |
| 5 | Freeze remaining pages to store | `market_data.py`, `option_chain.py`, `confluence.py`, `nifty_sentiment.py`, `vat.py`, scanners | PR-3 | Zero competing walks |

Each PR is independently shippable. PR-1 alone should already make Radar feel “wired”. PR-2 makes it fast. PR-3/4 make it complete.

---

## 17. Test plan (must pass before calling Radar “fixed”)

1. **Limiter unit:** `"Expecting value"` does **not** trip cooldown; `code=429` does.
2. **Writer isolation:** during `scan_all`, a fake HTTP thread calling `get_option_chain("NSE:NIFTY50-INDEX")` does not increment Fyers mock.
3. **Concurrency:** mock OC RTT=1.0s, 12 names, 4 workers, min_interval=0.33 → wall time **< 5s** (serial would be ~12s).
4. **Budget:** 187 OC in one pass → ≤ 190 limiter grants (quotes extra). No cooldown.
5. **Listing:** after 10 names, `GET /radar/last` has 10 scanned and any hits visible; job snapshot `flagged` non-empty before `completed`.
6. **Partial:** kill 20 names with errors → board still published, `partial=true`, frontend shows skipped, no “Previous board kept” fatal.
7. **Nudge:** UI Scan during scheduler pass does not start a second `scan_all`.
8. **Row click:** after harvest, `get_symbol_flow` with Redis populated → 0 limiter grants.
9. **Home hidden:** switch to Radar, 60s, NIFTY OC grant count does not climb from home widgets.
10. **Manual IST session:** 09:15–09:17 TOP 34 on screen; 09:16:30 ~187 attempted.

---

## 18. Open questions (defaults if unanswered)

| # | Question | Default if silent |
| ---: | :--- | :--- |
| 1 | Keep 180s full-book refresh or 90s for tier-0 only? | **Tier-0 every 90s, full book every 180s** (still ≤180 RPM). |
| 2 | Show skipped/error names as rows on the tape? | **Yes** — grey row, so listing is complete. |
| 3 | Redis required for local dev? | **Yes** via docker compose; memory fallback allowed but warned in `/ready`. |
| 4 | Kill Quant/VAT/HV buttons until store-only? | **Leave buttons**, return store data or “waiting for harvest”. |
| 5 | Use 5m history at all? | **No** on harvest. 15m is enough for VWAP/OR. Detail view can request 5m only when actor idle. |

---

## 19. What not to do

- Do not raise limiter to 10 RPS “to go faster”.
- Do not fetch 3-day option-contract history per candidate (187×4 extra history).
- Do not `force_refresh` chains on every retry.
- Do not wait 6×45s on one name.
- Do not blank the board at scan start (already avoided) **or** at partial finish (still happens).
- Do not start HV / 7/200 / stocks-quant walks from Radar.
- Do not rewrite `radar_signal_engine` as part of the speed project.
- Do not add a second cache layer; finish `symbol_store` as the book.

---

## 20. Success metric

Radar is “fully functional and fast” when, on a normal traded day with Redis up and a valid Fyers token:

- **≤15s:** NIFTY, BANKNIFTY, FINNIFTY, and TOP F&O names show live OI grades or explicit skip.
- **≤75s:** all 187 names have been attempted this pass; the tape lists them.
- **Limiter:** 0 cooldowns in a clean hour; RPM peak ≤180.
- **Click:** chain widget opens from store without stalling the harvest.
- **Quota:** Fyers does not return 429 during the chain window.

That is the architecture. Implement in PR order in §16.
