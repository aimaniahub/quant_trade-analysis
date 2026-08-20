# routingfix.md

**Status:** PLAN ONLY — do not implement until this doc is reviewed.  
**Goal:** One harvest (Flow Radar) writes a full per-symbol snapshot into Redis. Every other page / strategy **reads Redis**. Fyers is called only to refresh the store.

---

## 0. What you asked for (in one sentence)

When Flow Radar (or the scheduler) walks the F&O book, that **same pass** should fetch everything every strategy needs, **store/update Redis**, and when you switch to VAT / 7/200 / High Vol / Quant / Confluence / Option Chain, those screens **must not hit Fyers again** — they compute from the Redis snapshot that radar already keeps warm.

---

## 1. Problem

### 1.1 Symptom

Fyers quota is burned by **overlapping loops**, not by a single radar scan.

Today each feature is a private pipeline:

```
UI page  →  FastAPI route  →  service  →  fyers_market.get_*  →  Fyers
```

Several pages do this **on a timer at the same time**. Redis exists, but it is used as a **tiny short-TTL cache of raw REST payloads**, not as a **shared market store**.

### 1.2 What already exists (and why it is not enough)

| Piece | File | What it does | Gap |
| :--- | :--- | :--- | :--- |
| Docker Redis | `docker-compose.yml` | `redis:7-alpine` on `6379` | Already there. Use it. |
| Redis client | `backend/app/services/redis_client.py` | JSON get/set, prefix `optiongreek:` | Helpers only. No symbol schema. |
| MarketCache L1+L2 | `backend/app/services/market_cache.py` | 3–180s TTL on quotes / OC / history | Keys include `strike_count` and `days`. Same stock, different callers = **miss**. |
| Scan jobs | `backend/app/services/scan_jobs.py` | Job progress in Redis | Stores **results**, not reusable market data. |
| Radar last scan | `option_flow_radar._persist_last_scan` | `optiongreek:radar:last_scan` TTL 1800s | Only **flagged board**, not full chains. |
| Idea book | `idea_book.py` | `optiongreek:radar:idea_book` TTL 8h | Process trades only. |
| Chain snapshots | `chain_snapshots.py` | Slim ATM straddle/OI | Not a full chain. |
| Tech cache | `tech_filters.py` | `optiongreek:tech:*` | MA-only fragment. |
| Shared universe | `shared_universe.py` | Collects **symbol names** already touched | Does **not** share the data. |
| Rate limiter | `rate_limiter.py` | ~2.5–3 req/s, 45s cooldown | Slows the stampede; does not remove it. |
| Scheduler | `radar_scheduler.py` | TOP-FNO every **600s** while open | Parallel to UI 90s full-universe scan. |

**Config today** (`backend/.env.example`):

```
REDIS_ENABLED=true
REDIS_URL=redis://localhost:6379/0
REDIS_PREFIX=optiongreek
```

`config.py` default is still `redis_enabled: bool = False`. Prod/local must keep `REDIS_ENABLED=true`.

### 1.3 Cache TTLs (current)

From `fyers_market.py`:

| Payload | TTL | Effect |
| :--- | ---: | :--- |
| Quotes / spot | **3s** | Home indices poll every 15s → almost always miss. |
| Option chain | **8s** | Every 45s OC / 30s signal / 90s radar = miss. |
| History (generic) | **45s** | |
| History 15m / 5m / 30m | **180s** | 7/200 still uses `force_refresh=True` and **bypasses** this. |

Cache key = `md5(prefix, symbol, strike_count, days, …)`.

So:

- Radar scan `strike_count=8` (UI `startScan`)
- Scheduler `strike_count=10`
- Process attach `strike_count=12`
- Stock scan `strike_count=10`
- Live signal `strike_count=20`
- Greeks heatmap `strike_count=15`
- Home chain `strike_count=10`
- Confluence Nifty `strike_count=8`
- VAT Nifty `strike_count ≈ (500/50)*2+10 = 30`

**Same NIFTY option chain is fetched 4–6 times as different keys.**

---

## 2. Universe and Fyers budget

| Set | Size | Used by |
| :--- | ---: | :--- |
| `FNO_STOCKS` | ~186 equities | HV, 7/200, stock scan, radar |
| `FNO_INDICES` | 3 (Nifty, BankNifty, FinNifty) | Radar, VAT, home |
| `TOP_FNO_STOCKS` | 30 | Scheduler, “top” scans |
| Radar watchlist `ALL_FNO_WATCHLIST` | **~189** | UI Flow Radar full scan |

Fyers retail: roughly **~10 req/s**, plus daily/burst. Internal limiter: **~2.5–3 req/s**.

### 2.1 What **one** radar symbol costs today (`scan_all` → `_process_option_chain` → `_attach_process_trade`)

Always (every symbol):

1. `get_spot_price` → `quotes` (1 symbol)
2. `get_option_chain` (1)

If the chain produces fuel (grade B+ / A):

3. Upgrade light → full: `history` **5m / 1 day**
4. Optional `history` **D / 5 days** on the **option contract** (`_get_3day_vol_avg`)
5. Levels day map: `history` **D / 25 days**
6. Futures: `quotes` on `NSE:SYMBOL + expiry` future
7. MTF: `history` **D / 30d**, **240 / 45d**, **60 / 15d**, **15 / 6d**

**Worst case ≈ 2 + 7 = 9 Fyers calls per hot symbol.**  
**Cold symbol ≈ 2 calls.**

UI radar: `startScan` over **189 names**, auto-repeat **every 90 seconds** while the page is open.

```
189 × 2 = 378 calls minimum per UI pass
+ extra 5–7 per flagged (~30–40 names) ≈ +200
≈ 550–600 Fyers calls / 90s
```

Plus scheduler every 10 min on 33 names.  
Plus home / quant / VAT timers if those pages are also mounted (or if user switches quickly).

That is the waste.

---

## 3. Map: every UI page → routes → Fyers

Dashboard shell (`Dashboard.tsx`) is the only router. Each view below is a full page or a home-panel.

### 3.1 Home (`currentView === 'dashboard'`)

| Widget | Frontend | Poll | Backend route | Fyers |
| :--- | :--- | ---: | :--- | :--- |
| Market indices | `MarketIndices.tsx` | **15s** | `GET /market/indices` | `quotes` on 3–4 indices |
| Market state | `MarketStateDetector.tsx` | **45s** | `GET /market/state` | **NIFTY OC ±10** |
| Active strategy | `ActiveStrategy.tsx` | **45s** | same `/market/state` | **same OC again** (separate React Query key) |
| Option chain table | `OptionChainTable.tsx` | **45s** | `GET /options/chain/NSE:NIFTY50-INDEX` | **NIFTY OC ±10** (3rd copy) |
| Confluence | `ConfluencePanel.tsx` | **60s** | `GET /confluence` | Reads radar cache + idea book, **then another NIFTY OC ±8** in `_safe_nifty_intel` |
| Alerts | `RealTimeAlerts` / `alerts-hub.ts` | WS + **30s** REST | `/ws/alerts`, `GET /alerts/recent` | none (bus) |
| System status | `SystemStatus.tsx` | **20s** | `GET /ready`, `GET /auth/status` | none |
| **Run radar** button | Confluence | click | `POST /confluence/radar/scan` | **full TOP-FNO radar** |

Home alone: **3 independent NIFTY option-chain fetches every ~45s**, plus quotes every 15s.

### 3.2 Flow Radar (`OptionFlowRadar.tsx`) — **the writer we will keep**

| Action | Interval | Route | Fyers |
| :--- | :--- | :--- | :--- |
| `getLastScan` on mount | once | `GET /radar/last` | none (memory/Redis board) |
| `getIdeas` | **30s** | `GET /radar/ideas` | none |
| `startScan` + poll job | mount + **every 90s** | `POST /radar/scan/start`, `GET /radar/scan/jobs/{id}` | **full 189-symbol harvest** |
| Row click `loadFlow` | click | `GET /radar/flow/{symbol}` | OC + 5m history + process attach (if cache cold) |
| Backtest | click | `POST /radar/backtest` | 5m history |
| Background scheduler | **600s** open | internal `RadarScheduler.run_once` | TOP 33 symbols, **same** `scan_all` |

**This page is both the product and the stampede.** After the fix, this page (plus scheduler) is the **only** Fyers writer. The 90s UI rescan must stop; UI only reads Redis.

### 3.3 Quant Dashboard

| Widget | Poll | Route | Fyers |
| :--- | ---: | :--- | :--- |
| High-vol picker | once on load | `GET /market/high-volume-scan?timeframe=60` | **history 60m × ~186 stocks** |
| Nifty sentiment | **30s** | `GET /market/nifty-sentiment` | VIX quote + **3× NIFTY OC** (PCR, OI, levels) + **50 individual spots** |
| Live trade signal | **30s** | `GET /market/live-trade-signal/{sym}` | **OC ±20** + idea book override |
| Greeks heatmap | **30s** | `GET /market/greeks-heatmap/{sym}` | **OC ±15** (4th chain for same symbol) |

Sentiment `get_market_breadth` loops `FNO_STOCKS[:50]` with **one quote each** instead of one batched `quotes` of 50.

### 3.4 Stocks Option (`StockAnalysis.tsx`)

| Action | Route | Fyers |
| :--- | :--- | :--- |
| Start / retry job | `POST /market/stocks/scan/start` | **OC per symbol** (limit 200, `deep=true`) |
| Poll 1.5s | `GET /market/stocks/scan/jobs/{id}` | none |

This is a second full-universe option-chain walk, independent of radar.

### 3.5 VAT Scanner

| Action | Interval | Route | Fyers |
| :--- | ---: | :--- | :--- |
| Scan | **45s** | `GET /strategies/vat/scan?symbol=` | **wide OC** (Nifty ~30 strikes) + spot + VIX + optional 15m history |

### 3.6 7/200 Cross (`MA7200Scanner.tsx`)

| Action | Route | Fyers |
| :--- | :--- | :--- |
| Start scan | `POST /strategies/ma7200/scan/start` | **`history 15m / 40d` per symbol with `force_refresh=True`** — **cache bypass** |
| Analyze chain | `GET /strategies/ma7200/analyze` | **OC ±12** |

~186 extra history calls even if radar just pulled 15m.

### 3.7 High Volume

| Action | Route | Fyers |
| :--- | :--- | :--- |
| Start | `POST /market/high-volume-scan/start` | **history 15m or 60m / 5d × 186** |
| Bulk OC | `POST /market/bulk-oc-analysis` | **OC × top 5** |

### 3.8 Trading (MCP)

| Action | Route | Fyers |
| :--- | :--- | :--- |
| Status / tools / orders | `/mcp/*` | funds, positions, place order — **not market harvest**. Leave as-is. |

### 3.9 Auth / health (no market waste)

`/auth/*`, `/health`, `/ready` — keep.

### 3.10 Dead / disabled (do not revive as a second harvester)

Legacy multi-TF MA (`/ma-crossover/*`) is **disabled** in `main.py` and `ma_crossover.py` start/scan. UI was removed. Do **not** turn auto-scan back on. 7/200 is the MA product.

---

## 4. Map: each strategy → data it actually needs

This is the contract the harvest must satisfy. If a field is in this table, radar must write it (or a parent that can derive it). If it is not, do not fetch it on the hot path.

### 4.1 Shared primitives (every stock)

| Field | Source | Used by |
| :--- | :--- | :--- |
| `spot` (ltp, chg, chg%, high, low, open, prev_close, volume) | `quotes` | all |
| `option_chain` ATM-centric, **canonical ±14 strikes** | `optionchain` | radar, VAT (slice), 7/200 confirm, stock intel, live signal, greeks, HV OC, home Nifty |
| `expiries`, `atm`, `pcr`, `india_vix` (on index) | same OC response | radar, intel, VAT |
| `updated_at` | harvest clock | all readers (staleness) |

### 4.2 Flow Radar / process idea / execution / OI clusters

| Field | Source | Notes |
| :--- | :--- | :--- |
| Full OC legs: LTP, OI, OI Δ%, volume, IV, bid/ask, greeks | OC | LIS, grade, CE/PE matrix |
| 5m or 15m session bars | history | VWAP, EMA20, OR; 15m can **derive** VWAP if we accept slightly coarser session |
| Daily bars ≥ 20 | history D | PDH/PDL, classic/Camarilla/CPR, ATR |
| Futures LTP + OI | `quotes` on future | buildup / covering |
| MTF stacks D / 4H / 1H / 15m | history **or derive 4H/1H from 15m** | `mtf_engine` |
| Computed: LIS, grade, idea, execution plan, clusters | **CPU only** | `idea_engine`, `execution`, `oi_clusters`, `levels` |

### 4.3 7/200 MA + OC confirm

| Field | Need | Harvest? |
| :--- | :--- | :--- |
| 15m OHLCV, **≥ 205 bars** (~40 calendar days) | **required** | **Yes — one 15m/40d per symbol** |
| OC ±12 + intel summary | only for **candidates** (Analyze) | Read stored OC; recompute intel in process |

Today: `force_refresh=True` → never reuse. After fix: **read Redis 15m**. Freshness: 15m bar only changes once per 15 minutes. TTL **900s** is correct.

### 4.4 High Volume

| Field | Need | Harvest? |
| :--- | :--- | :--- |
| 15m last **5 days** (or 60m last 5d) | relative volume, buying pressure | **Subset of the same 15m/40d** |
| OC for top 5 | scoring | stored OC |

No extra Fyers if 15m/40d is in Redis.

### 4.5 VAT (Nifty / BankNifty only)

| Field | Need | Harvest? |
| :--- | :--- | :--- |
| **Wide** OC (Nifty ±500 ≈ 20–30 strikes) | equidistant premium gaps | Harvest indices with `strike_count=20` (not 14) |
| Spot | yes | quotes |
| VIX | context | one quote, store under `NSE:INDIAVIX-INDEX` |
| 15m history | momentum score | stored 15m |

VAT does **not** need 186 stock chains. Only 2–3 index chains, but **wider**.

### 4.6 Stock Analysis / F&O intelligence / live signal / greeks

| Field | Need | Harvest? |
| :--- | :--- | :--- |
| OC ±10–20 | PCR, OI walls, ATM, greeks table | stored OC ±14 is enough if we **always harvest 14** |
| Intel / desk decision / trade rec | CPU on that chain | no Fyers |

`analyze_stock` / `get_analysis_summary` / `_generate_trade_recommendation` take a **chain dict**. They must accept the Redis snapshot.

### 4.7 Nifty sentiment cards

| Field | Need | Harvest? |
| :--- | :--- | :--- |
| VIX quote | 1 | store with indices |
| Nifty OC ±20 | PCR, OI change, S/R | **one** index snapshot — stop 3× OC |
| Breadth | advance/decline | **use stored spots of 50 names**, not 50 new quotes |

### 4.8 Confluence

| Field | Need | Harvest? |
| :--- | :--- | :--- |
| Radar last flagged | already Redis | keep |
| Idea book | already Redis | keep |
| MA crosses | 7/200 results from Redis 15m | no live MA service |
| Nifty intel | from stored Nifty OC | **delete** extra `get_option_chain(±8)` |

### 4.9 Home option chain + market state

Same Nifty snapshot. One Redis key. Two widgets.

### 4.10 Levels / MTF / execution (libraries, not pages)

They must become **pure functions of the snapshot**:

```
build_full_map(symbol, spot, chain, candles_5m|15m, dailies, futures_quote)
evaluate_mtf(daily, h4, h1, m15)   # h4/h1 derived from 15m
plan_execution(...)
detect_oi_clusters(chain, spot)
```

Today `levels.get_day_map` and `mtf_service._candles` **call Fyers themselves**. That is the leak on every attach. After fix they **only read** `snapshot.history.D` / `snapshot.history.15`.

### 4.11 What we will **not** harvest every pass

| Data | Why skip |
| :--- | :--- |
| Option-contract 3-day volume (`_get_3day_vol_avg`) | Extra history **per option symbol**. Use chain-relative volume (already in radar). |
| Market depth / L2 | Unused by strategies. |
| 1m candles | Charts can request on click, or downsample 5m. |
| Full 4H/1H REST | Derive from 15m. |
| 186 futures quotes every pass | Batch **only flagged / idea symbols**, or one futures batch per 10 min. |
| Grok news | Already cached separately. |

---

## 5. Target architecture

```
                    ┌──────────────────────────────┐
                    │   Flow Radar harvest loop     │
                    │   (scheduler = owner)         │
                    │   UI only reads + “refresh”   │
                    └──────────────┬───────────────┘
                                   │ Fyers (batched)
                                   ▼
                    ┌──────────────────────────────┐
                    │     Redis Symbol Store        │
                    │  optiongreek:sym:{SYMBOL}     │
                    │  optiongreek:idx:quotes       │
                    │  optiongreek:meta:harvest     │
                    └──────────────┬───────────────┘
           ┌───────────┬───────────┼───────────┬───────────┐
           ▼           ▼           ▼           ▼           ▼
        Radar UI     7/200       VAT        HV/Quant    Home/Confluence
        ideas        filter      gaps       rel-vol     OC + state
        (CPU)        (CPU)       (CPU)      (CPU)       (CPU)
```

**One writer. Many readers. CPU is free. Fyers is not.**

### 5.1 Ownership

| Role | Who | Rule |
| :--- | :--- | :--- |
| Writer | `RadarScheduler` (+ optional manual “Refresh book”) | Only process allowed to call Fyers for **universe** data |
| Readers | every route/service listed in §3 | `store.get(symbol)` or `store.get_index("NIFTY")` |
| Bypass | MCP orders, auth, user-clicked backtest, **single-symbol refresh if snapshot older than stale_hard** | Rare |

### 5.2 Harvest cadence (replace 90s UI + 600s TOP)

| Window | What | Why |
| :--- | :--- | :--- |
| Market open | Full book every **180–240s** (not 90) | OC/OI does not need sub-minute; limiter can finish ~189×(quote-batch + OC) in ~2 min |
| Per symbol inside pass | OC + upsert Redis immediately | UI sees progressive updates (already have job poll) |
| 15m history | Refresh when **bar closed** or age > 900s | 7/200 / HV / MTF |
| Daily history | Once per IST date (already how `levels._day` works) | Almost free after first pass |
| Quotes batch | Every harvest (4 calls of 50) | Replaces 189 `get_spot_price` |
| Market closed | No harvest. Readers serve last snapshot. | Scheduler already sleeps |

**Delete** the frontend `setInterval(runScan, 90_000)`.  
UI `GET /radar/last` + `GET /radar/ideas` every 15–30s is enough.

### 5.3 Canonical fetch sizes (one key, many consumers)

| API | Canonical args | Serves |
| :--- | :--- | :--- |
| quotes | batches of ≤50, all EQ + 3 indices + VIX | spots, breadth, indices widget |
| optionchain | **`strikecount=14`** equities; **`20`** for 3 indices | radar, intel, greeks, live signal, home, 7/200 confirm; VAT uses 20 |
| history 15 | **days=40** | 7/200, HV 5d, MTF 15m, derive 60m/4H |
| history D | **days=30** | levels, MTF daily |
| history 5 | **only on row-click chart**, or skip if 15m enough | radar detail chart |

`fyers_market.get_option_chain(symbol, strike_count)` after the fix:

1. Load Redis snapshot.
2. If snapshot chain width ≥ requested and not stale → **slice** to `strike_count` and return.
3. Else only the **writer** may fetch.

Never key cache by `strike_count` again.

---

## 6. Redis schema (concrete)

Prefix: `optiongreek` (existing).

### 6.1 Per-symbol document

**Key:** `optiongreek:sym:{SYMBOL}`  
Example: `optiongreek:sym:NSE:SBIN-EQ`

```json
{
  "symbol": "NSE:SBIN-EQ",
  "name": "SBIN",
  "kind": "EQ",
  "harvest_ts": 1786698000.1,
  "harvest_iso": "2026-08-14T16:40:00+05:30",
  "source": "radar_harvest",
  "spot": {
    "ltp": 812.4,
    "chg": 2.1,
    "chg_pct": 0.26,
    "open": 810,
    "high": 818,
    "low": 808,
    "prev_close": 810.3,
    "volume": 12345678
  },
  "chain": {
    "strike_count": 14,
    "spot_price": 812.4,
    "atm_strike": 810,
    "pcr": 0.92,
    "expiries": ["..."],
    "india_vix": null,
    "rows": [ { "strike_price": 800, "call": {}, "put": {} } ]
  },
  "history": {
    "15": { "days": 40, "candles": [ /* ohlcv */ ], "ts": 1786698000 },
    "D":  { "days": 30, "candles": [ /* ohlcv */ ], "ts": 1786698000 }
  },
  "futures": {
    "symbol": "NSE:SBIN25AUGFUT",
    "ltp": 814.0,
    "oi": 0,
    "oi_chg": 0,
    "ts": 1786698000
  },
  "derived": {
    "vwap": 811.2,
    "ema20_15": 809.1,
    "rel_vol_15": 1.8,
    "ma7200": { "cross": null, "bars_ago": null, "fast": 1, "slow": 2 },
    "mtf": { "daily_bias": "BULLISH", "h4_bias": "...", "h1_bias": "...", "m15_bias": "..." }
  }
}
```

**TTL:** 4 hours (so an evening restart still has a book; harvest refreshes in-session).  
Do **not** use 8-second TTL. That is the current bug.

**Size note:** 15m × 40d ≈ 650 bars × ~6 numbers ≈ small. Full OC 29 rows × 2 legs is small. One symbol JSON ≈ 80–200 KB. 189 symbols ≈ **20–40 MB**. Redis 256 MB cap in compose is enough.

### 6.2 Index / meta keys

| Key | Type | Purpose |
| :--- | :--- | :--- |
| `optiongreek:meta:harvest` | JSON | `{running, started_at, finished_at, scanned, total, current, pass_id}` |
| `optiongreek:idx:symbols` | SET or JSON list | universe this pass |
| `optiongreek:idx:quotes` | HASH `symbol → spot json` | cheap breadth / indices |
| `optiongreek:idx:stale` | ZSET score=`harvest_ts` | harvest next-oldest first |
| `optiongreek:radar:last_scan` | JSON | **keep** — UI board (flagged/ideas). Already exists. Raise TTL to 4h. |
| `optiongreek:radar:idea_book` | JSON | **keep** |
| `optiongreek:job:*` | JSON | **keep** scan job progress |
| `optiongreek:ocsnap:*` | slim ATM | optional; can die once full chain is stored |

### 6.3 New module (to add later)

`backend/app/services/symbol_store.py`

```
get(symbol) -> snapshot | None
put(symbol, patch)          # merge + set harvest_ts
get_many(symbols) -> dict
list_fresh(max_age) -> [symbol]
is_fresh(symbol, field, max_age)
get_chain(symbol, strike_count) -> sliced chain or None
get_history(symbol, resolution, min_bars) -> candles or None
get_spots(symbols) -> {symbol: spot}
set_harvest_meta(...)
```

Memory fallback if Redis down (same pattern as `redis_client` today). **Do not crash** if Docker Redis is off.

---

## 7. How the harvest should work (process)

This is the implementation algorithm. No code yet.

### Pass A — quotes (cheap, batched)

1. Universe = `filter_valid_symbols(FNO_STOCKS + FNO_INDICES + [VIX])`.
2. `quotes` in chunks of 50 → **4–5 Fyers calls**.
3. `store.put(sym, {spot})` + `idx:quotes`.

**Replaces:** 189 `get_spot_price`, 50 sentiment spots, 3 index widget polls, VIX.

### Pass B — option chains (the expensive one)

For each symbol (pace 0.35s, respect limiter):

1. If `store.get_chain(sym)` age < `OC_TTL` (e.g. 90–120s) **and** width ≥ canonical → skip Fyers.
2. Else `optionchain(strikecount=14)` (20 if index).
3. `store.put(sym, {chain})` immediately (UI can already show this name).
4. Run **CPU** radar grade / idea ingest **from that chain + stored spot**. No second OC.

**Replaces:** stock scan OC, live signal OC, greeks OC, HV bulk OC, 7/200 analyze OC, home Nifty OC, confluence Nifty OC, sentiment’s 3 Nifty OCs.

### Pass C — history (slow fields, not every 90s)

Per symbol, independently:

- If `history.15` missing or age > 900s → fetch 15m/40d → store.  
  Derive 60m and 4H in process. Run 7/200 + HV scoring into `derived`.
- If `history.D` missing or IST date changed → fetch D/30d → store. Build day map into `derived` or leave for levels CPU.

**First open of the day:** ~189 × 2 history = 378 calls, once.  
**Rest of day:** only 15m refresh ~every 15 minutes, can be **round-robin 20 names/min** instead of a burst.

### Pass D — futures (optional, flagged only)

Batch `quotes` for futures of symbols that have fuel. Store under `snapshot.futures`.

### After each symbol in B+C

- `idea_book.ingest` if fuel
- Update `radar:last_scan` incrementally (already streamed via scan jobs)
- `derived.mtf = evaluate_mtf(stored D, derived 4H, derived 1H, stored 15)`

**No extra Fyers inside attach.**

---

## 8. How each route should change (reader contract)

Do **not** implement now. This is the routing fix list.

| Route | Today | After |
| :--- | :--- | :--- |
| `GET /radar/scan/start` | Starts Fyers walk | Starts harvest **or** returns “scheduler owns it”; UI polls `last` + `harvest` meta |
| `GET /radar/last` | last board | unchanged (Redis) |
| `GET /radar/ideas` | idea book | unchanged |
| `GET /radar/flow/{sym}` | new OC + 5m | **store.get**; optional 5m only if chart empty |
| `GET /radar/levels/{sym}` | `build_full_map` + Fyers | CPU on stored D + chain + 15m |
| `GET /options/chain/{sym}` | Fyers OC | `store.get_chain` |
| `GET /options/analysis/{sym}` | Fyers OC + intel | stored chain + intel |
| `GET /market/state` | Fyers OC + intel | stored Nifty chain + intel |
| `GET /market/indices` | Fyers quotes | `idx:quotes` for index symbols |
| `GET /market/spot/{sym}` | Fyers | `snapshot.spot` |
| `GET /market/nifty-sentiment` | 3 OC + 50 spots | 1 stored Nifty chain + VIX + 50 stored spots |
| `GET /market/live-trade-signal/{sym}` | OC ±20 | stored chain + intel + idea book |
| `GET /market/greeks-heatmap/{sym}` | OC ±15 | stored chain |
| `GET /market/stocks/scan*` | OC × N | **CPU intel over store** for all fresh symbols; no Fyers |
| `GET /market/high-volume-scan*` | history × N | **CPU** on `history.15` |
| `POST /market/bulk-oc-analysis` | OC × list | stored chains |
| `GET /strategies/vat/scan*` | wide OC | stored index chain (width 20) |
| `GET /strategies/ma7200/scan*` | force 15m × N | **CPU** 7/200 on `history.15`; drop `force_refresh` |
| `GET /strategies/ma7200/analyze` | OC | stored chain + intel |
| `GET /confluence` | extra Nifty OC | stored Nifty + idea book + 7/200 derived |
| `GET /market/history/{sym}` | Fyers | stored history; Fyers only if field missing + writer |

Frontend poll changes (same files, later PR):

| File | Change |
| :--- | :--- |
| `OptionFlowRadar.tsx` | Remove 90s `runScan`. Poll `/radar/last` + `/radar/ideas` + harvest meta. Manual “Refresh book” only. |
| `OptionChainTable.tsx` | Keep 45s; backend will be Redis. |
| `MarketStateDetector` + `ActiveStrategy` | **Share one React Query key** `['market','state','NIFTY']` — they already hit the same route. |
| `MarketIndices.tsx` | 15s → 30–45s (quotes live in store). |
| `NiftySentimentCards` | 30s OK; backend no longer explodes. |
| `LiveTradeSignal` / `GreeksHeatmap` | Keep; backend Redis. |
| `VATScanner` | 45s OK; Redis. |
| `QuantDashboard` | Stop calling `scanHighVolume` as a blocking Fyers walk; `GET` derived HV from store. |
| `ConfluencePanel` | “Run radar” = “nudge harvest”, not a second parallel `scan_all`. |

---

## 9. Estimated call reduction

Assume market hours, user sits on Flow Radar, occasionally opens Quant / 7/200 / VAT.

| Caller | Before (per 10 min) | After (per 10 min) |
| :--- | ---: | ---: |
| UI radar 90s × 189 × ~2 | ~2,500+ | **0** (read Redis) |
| Scheduler TOP 33 | ~80 | **merged into one harvest** |
| Home 3× Nifty OC | ~40 | **0** |
| Sentiment 3 OC + 50 spots | ~160 | **0** |
| 7/200 force 15m × 186 | 186 (when opened) | **0** if history warm |
| HV 15m × 186 | 186 (when opened) | **0** |
| Stock scan OC × 186 | 186 (when opened) | **0** |
| **Harvest writer** | — | quotes 5 + OC ~189 + 15m refresh ~40 + D 0 (after morning) ≈ **230–250** |

**Order-of-magnitude: 10× fewer Fyers calls**, and features get **faster** (Redis ms vs Fyers 200–800ms each).

---

## 10. Implementation plan (phased — do not skip)

Each phase is a shippable PR. Do not rewrite radar scoring.

### Phase 0 — Stop the obvious stampede (no new store yet)

**Why first:** 50% of the waste is duplicate keys + double loops. Low risk.

1. Canonical `strike_count=14` (20 indices) in **all** OC callers. Same `make_key` hits.
2. Raise `TTL_OPTION_CHAIN` 8 → **90**. `TTL_QUOTES` 3 → **15**. Keep 15m history 180 or raise to **900**.
3. `get_quotes` batch in `nifty_sentiment.get_market_breadth` (50 names, 1 call).
4. `get_full_sentiment` call Nifty OC **once**, reuse for PCR / OI / levels.
5. Home: one React Query key for market state (Detector + ActiveStrategy).
6. Flow Radar: **remove 90s auto `runScan`**. Keep last-scan + ideas poll. Scheduler remains the writer.
7. Confluence: stop `_safe_nifty_intel` extra OC if `/market/state` just ran; or read radar/intel cache.
8. 7/200: remove `force_refresh=True`; honor history cache.

**Files:** `fyers_market.py`, `nifty_sentiment.py`, `OptionFlowRadar.tsx`, `ActiveStrategy.tsx`, `MarketStateDetector.tsx`, `ma7200_scanner.py`, `confluence.py`, radar UI `startScan(..., 8)` → 14.

**Do not** change scoring formulas.

### Phase 1 — `symbol_store.py` + harvest write path

1. Add `symbol_store.py` with schema §6.
2. In `scan_all`, after each successful OC + spot, `store.put`.
3. After 15m/D fetch (when they happen), `store.put` history.
4. Persist harvest meta.
5. `GET /market/store/status` (or extend `/ready`) → `{symbols, freshest, oldest, redis}`.
6. Raise `radar:last_scan` TTL 1800 → 14400.

**Files:** new `symbol_store.py`, `option_flow_radar.py`, `main.py` (nothing else yet).

### Phase 2 — `fyers_market` reads store first

Change `get_option_chain`, `get_quotes` / `get_spot_price`, `get_historical_data`:

```
hit = store.get(...)
if fresh: return hit
if caller is harvest: fetch Fyers → store.put → return
else: return stale hit if any, else fetch Fyers (escape hatch) and log "reader_miss"
```

Log `reader_miss` so we can see leaks.

**Files:** `fyers_market.py`, `symbol_store.py`.

After this, **VAT / stock scan / live signal / greeks / home OC automatically stop hitting Fyers** whenever radar has run in the last 90s. No per-route rewrite required yet.

### Phase 3 — Harvest the 7/200 / HV / MTF fields inside radar

1. During harvest, if `history.15` stale → fetch 40d once; derive 60/240; write `derived.ma7200` + `derived.rel_vol_15`.
2. If `history.D` missing today → fetch 30d.
3. `levels.get_day_map` / `mtf_service._candles` → **store only**.
4. Drop option-contract 3-day vol history (use peer volume).
5. 7/200 `scan_universe` = loop store histories, no Fyers.
6. HV `scan_high_volume_stocks` = loop store 15m.
7. QuantDashboard HV picker reads last derived list from Redis (`optiongreek:idx:hv` written each harvest).

**Files:** `option_flow_radar.py`, `levels.py`, `mtf_service.py`, `ma7200_scanner.py`, `high_volume_scanner.py`, `QuantDashboard.tsx`.

### Phase 4 — Route + UI polish

1. Stock scan job becomes “intel over store” (seconds, not minutes).
2. `/radar/flow` never fetches OC if store fresh; 5m chart optional.
3. `/confluence` 100% store + idea book + derived MA.
4. Frontend harvest banner: “Book age 42s · 189/189 · Redis”.
5. Document `REDIS_ENABLED=true` as required for prod (memory fallback still works for one worker).

### Phase 5 — Hardening

1. Snapshot compression if Redis memory grows (msgpack optional; JSON is fine at 40 MB).
2. `SCAN` + delete old `optiongreek:mkt:*` short-TTL keys (legacy MarketCache L2) so we do not double-write.
3. Unit tests around store slice/stale (user said remove tests earlier — add only a small `test` later if wanted; not required for this plan).
4. If harvest aborted on 429: serve stale store, do not empty the UI (already the last-scan pattern).

---

## 11. Files that will be touched (when implementing)

**New**

- `backend/app/services/symbol_store.py`

**Backend writers / readers**

- `backend/app/services/option_flow_radar.py` — harvest + put
- `backend/app/services/radar_scheduler.py` — own the cadence; maybe 180s full book instead of 600s TOP-only
- `backend/app/services/fyers_market.py` — store-first
- `backend/app/services/levels.py` — no Fyers
- `backend/app/services/mtf_service.py` — no Fyers
- `backend/app/services/nifty_sentiment.py` — one chain, batched quotes
- `backend/app/services/strategies/ma7200_scanner.py` — no force_refresh
- `backend/app/services/high_volume_scanner.py` — history from store
- `backend/app/services/confluence.py` — no extra OC
- `backend/app/routes/market_data.py` — state / live / greeks / stock scan read store
- `backend/app/routes/option_chain.py` — read store
- `backend/app/routes/option_flow_radar.py` — flow/levels read store
- `backend/app/core/config.py` — harvest TTLs / `HARVEST_OC_STRIKES=14` / `HARVEST_INTERVAL_SECS`

**Frontend**

- `frontend/components/OptionFlowRadar.tsx` — kill 90s rescan
- `frontend/components/ActiveStrategy.tsx` + `MarketStateDetector.tsx` — shared query key
- `frontend/components/QuantDashboard.tsx` — HV from store
- `frontend/lib/api.ts` — optional `api.store.status()`

**Do not touch** (scoring / recipes stay)

- `idea_engine.py`, `execution.py`, `oi_clusters.py`, `radar_signal_engine.py`, `option_analytics.py`, `desk_decision.py`, `vat.py` (logic), `fno_intelligence.py` (logic)

---

## 12. Risks and how to handle them

| Risk | Mitigation |
| :--- | :--- |
| First 3 minutes after 9:15 IST store is empty | Harvest immediately on market open (scheduler already waits 90s — **drop that delay** or cut to 5s). UI shows “warming book 12/189”. |
| Redis down | Memory fallback (current client). Single worker still works. Multi-worker needs Redis. |
| Payload too big | Do not store `all_hits` twice; chain + 15m + D is enough. |
| Stale trade on a fast name | `stale_soft` 90s (serve), `stale_hard` 300s (writer must refresh that symbol on next tick or on `flow` click). |
| VAT needs wider index chain | Harvest indices at 20. Equities stay 14. |
| 7/200 needs 200 bars | 40d 15m is ~650 bars. Confirm on first harvest; if short, one extra history call for that symbol only. |
| Futures symbol format | Keep existing `fut_symbol_for`; batch later. |
| Changing strike_count mid-flight | Canonical 14 only. Slice down. Never fetch 8 vs 10 vs 12 again. |
| User opens 7/200 before first 15m pass | 7/200 scans **only symbols that have `history.15`**. Banner: “15m book 40/189 — waiting harvest”. No `force_refresh` storm. |

---

## 13. How to verify after implementation (later)

1. `docker compose up -d redis`
2. `REDIS_ENABLED=true` in `backend/.env`
3. Start app. Open Flow Radar **once**.
4. Redis CLI:

```
redis-cli
KEYS optiongreek:sym:*
GET optiongreek:meta:harvest
```

5. Open VAT / 7/200 / High Vol / Quant / Home **without** a new Fyers burst.  
   Watch `fyersRequests.log` or a new counter `store.reader_hits` vs `store.reader_miss`.
6. `/ready` shows `redis: ok` and harvest age.
7. Kill backend, restart: last board + symbol docs still there (TTL 4h).

---

## 14. Decision recap (for when you say “build”)

1. **Flow Radar harvest is the only universe Fyers client.**
2. **Redis holds the full per-symbol bundle** (spot + OC + 15m + D + derived).
3. **Strategies are functions of that bundle.**
4. **UI polls Redis-backed routes**, does not start parallel scans.
5. **Canonical OC width 14 (20 indices). Canonical 15m window 40 days.**
6. **Derive 1H/4H from 15m. Do not fetch them.**
7. **Phase 0 first** (TTL + stop 90s scan + batch quotes) even before the new store — that alone saves most of the quota.

---

## 15. Suggested build order when approved

```
Phase 0  (1 sitting)   stop leaks, no schema
Phase 1  (1 sitting)   symbol_store + radar writes
Phase 2  (1 sitting)   fyers_market store-first  → all pages inherit
Phase 3  (1 sitting)   15m/D harvest + 7/200/HV/MTF/levels go CPU-only
Phase 4  (half)        UI cadence + banners
```

No application code was changed for this document. Next step: approve Phase 0 (or the full plan) and implement in that order.
