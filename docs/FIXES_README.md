# OptionGreek — Full Project Fix Report

**Date:** 2026-08-11 (updated)  
**Purpose:** Master list of what was broken, what was fixed, and what still needs work.  
**Review this file before further development.**

---

## 1. How to read this document

| Status | Meaning |
|--------|---------|
| **DONE** | Implemented in this repo |
| **PARTIAL** | Improved; still has limits (API rate limits, data quality) |
| **TODO** | Not done — required for “full production” |
| **EXTERNAL** | Depends on keys, broker, or market hours — not pure code |

---

## 2. Your complaints → where they map

| You said | Root cause | Fix status |
|----------|------------|------------|
| Loading states not dynamic / not tied to data | Many pages used spinners or **fake timers** only | **DONE** shared `LoadingBanner` + real job progress on Stocks Option |
| Pages half-scan / only some stocks analyzed | Full F&O OC scan hits **Fyers 429**; long HTTP blocked UI | **DONE** background **scan jobs** + `completion_pct` + **Retry failed only** |
| Bullish header but Neutral below | Conflicting fields (`quant_bias` vs guidance vs deep panel) | **DONE** single `setup_side` field + aligned guidance |
| Strategies not coordinating | Silos (MA / VAT / Radar / HV / Intel) | **PARTIAL** confluence engine + signal bus; still not one decision brain |
| “Full working project” | Rate limits + no DB + manual token | **PARTIAL** — honest limits below |

---

## 3. Architecture reality check

| Layer | Design | Reality |
|-------|--------|---------|
| Data | Live Fyers WS + REST | Mostly **REST** + limited WS (MA/alerts) |
| DB | Time-series / Redis | **Redis optional** — durable jobs + L2 market cache; memory fallback |
| Strategies | Coordinated decision engine | **Modules** + confluence aggregator |
| Long scans | Job queue + progress | **DONE** in-process jobs for Stocks Option; Radar/HV still request-scoped |
| Auth | Daily token | Manual OAuth paste; auto-login stub |
| News | Grok | Wired; often **403** until key fixed (**EXTERNAL**) |

---

## 4. Critical security

| Item | Status | Notes |
|------|--------|--------|
| Unauthenticated order placement | **DONE** | `MCP_TRADING_ENABLED=false` by default; 403 when off |
| Optional `MCP_API_KEY` | **DONE** | Header `X-MCP-API-KEY` |
| No app-level user auth | **TODO** | Anyone on LAN can hit API if exposed |
| Token in `.env` / logs | **PARTIAL** | Local OK; never commit `.env` |
| PIN/TOTP in env | **TODO** | Rotate if ever committed |

---

## 5. Backend — data & reliability

| Item | Status | Detail |
|------|--------|--------|
| Market data short-TTL cache | **DONE** | L1 memory + L2 Redis; quotes ~3s, OC ~8s, history ~45s |
| Redis client + graceful fallback | **DONE** | `redis_client.py`; off/down → memory |
| Durable scan jobs (Redis) | **DONE** | Persist + index; orphan recovery on boot |
| Last radar scan in Redis | **DONE** | Confluence after restart |
| Process-wide Fyers rate limiter | **DONE** | Cooldown on 429 / request limit |
| Invalid symbol blacklist | **DONE** | e.g. `TATAMOTORS`→`TMPV`, `NIFTYFIN`→`FINNIFTY` |
| Fail-fast invalid symbols (MA) | **DONE** | No 3× retries on bad symbols |
| Auth reload → all services | **DONE** | Clears Fyers client, cache, WS settings |
| Token validation cache (60s) | **DONE** | Stops auth spam |
| Async routes + `to_thread` | **PARTIAL** | Major routes done |
| Full F&O stock scan | **PARTIAL** | Full universe attempted; 429 → partial |
| Scan `completion_pct` / `partial` | **DONE** | Response + UI |
| **Background scan jobs + poll API** | **DONE** | Stocks + Radar + High Volume |
| **Retry-failed-only** | **DONE** | `POST .../jobs/{id}/retry-failed` |
| **Merge retry into previous grid** | **DONE** | Server merge by symbol + client safety merge |
| **MA single WebSocket hub** | **DONE** | `frontend/lib/ma-crossover-hub.ts` (like alerts hub) |
| Radar / HV background jobs | **DONE** | `/radar/scan/start`, `/market/high-volume-scan/start` |
| Single `setup_side` | **DONE** | Bull/bear column consistency |
| Unbiased quant votes | **DONE** | Symmetric; ties = NEUTRAL; **buildup-weighted** |
| Option math | **DONE** | max pain, skew, γ-wall, straddle, VAT gaps |
| **Four canonical buildups** | **DONE** | Long/Short Buildup, Short Covering, Long Unwinding + strength |
| **PCR triad (OI / Vol / ATM / band)** | **DONE** | + India regime labels |
| **Call wall / Put wall** | **DONE** | First-class fields on scan + UI |
| **15m 7/20 EMA + volume** | **DONE** | `tech_filters.py` · HTF 20/50/200 gate |
| **Premium snapshot diffs** | **DONE** | Redis/memory OC snaps · squeeze / vol-expand |
| **Desk score fusion** | **DONE** | Hardened HTF→PCR→Buildup→Gamma→Skew→15m (`desk_decision.py`) |
| **Conflict → WAIT** | **DONE** | LICHSGFIN-style: Long Buildup vs ceiling/HTF never forces BUY |
| Confluence multi-source | **DONE** | MA + radar + intel + bus (+ soft news) |
| Radar scheduler | **DONE** | Top list, market hours, rate-limit aware |
| MA full-universe rotation | **DONE** | ~32/chunk, rotates ~187; manual = full |
| Grok news | **PARTIAL** | **EXTERNAL** key 403 |
| Automated Fyers login | **TODO** | Manual OAuth |
| Redis / DB persistence | **DONE** (optional) | Jobs + L2 cache + last radar scan; needs Redis running |
| True tick multi-TF MA | **TODO** | Needs dense WS |
| Background jobs for Radar / HV | **TODO** | Same pattern as stocks scan |
| Merge retry into previous job results | **TODO** | Retry starts **new** job; UI replaces with new set |

---

## 6. Backend — strategies (per module)

### 6.1 F&O Intelligence
| Item | Status |
|------|--------|
| MarketState ADJUSTMENT crash | **DONE** |
| IST time windows | **DONE** |
| Deep analytics attach | **DONE** |
| Strike guidance symmetric CE/PE | **DONE** |
| Futures basis / true institutional flow | **TODO** |
| Real delivery % | **TODO** (not in Fyers OC) |

### 6.2 MA Crossover
| Item | Status |
|------|--------|
| Rate-limit throttle + abort | **DONE** |
| consecutive_candles used | **DONE** |
| Invalid symbols filtered | **DONE** |
| Rotate full universe auto-scan | **DONE** |
| Incremental 1m MA cache on ticks | **PARTIAL** |
| Multi-TF from ticks | **TODO** |
| Single browser WS hub (like alerts) | **TODO** |

### 6.3 Option Flow Radar
| Item | Status |
|------|--------|
| LIS v2, best strike/stock | **DONE** |
| Cached last scan for confluence | **DONE** |
| Background TOP scan (scheduler) | **DONE** |
| Delivery ratio real | **TODO** (placeholder 1.0) |
| Job + live progress for full 180 scan | **DONE** |
| Frontend LoadingBanner | **DONE** |

### 6.4 VAT
| Item | Status |
|------|--------|
| Momentum candles key | **DONE** |
| Greeks top-level keys | **DONE** |
| IST windows | **DONE** |
| Max pain in VAT score | **PARTIAL** |
| Advanced endpoint fully used in UI | **TODO** (UI still mostly basic `/vat/scan`) |
| LoadingBanner | **DONE** |

### 6.5 High Volume Scanner
| Item | Status |
|------|--------|
| day_high field | **DONE** |
| to_thread history | **DONE** |
| LoadingBanner + honest progress label | **DONE** |
| Server-side job progress | **DONE** | `POST .../high-volume-scan/start` + poll |
| Full 200 scan reliability under 429 | **PARTIAL** |

### 6.6 Confluence
| Item | Status |
|------|--------|
| Multi-source score + UI | **DONE** |
| Unique source tags | **DONE** |
| LoadingBanner | **DONE** |
| News soft weight | **PARTIAL** (Grok key) |

### 6.7 MCP Trading
| Item | Status |
|------|--------|
| Kill-switch | **DONE** |
| Quotes/OC field mapping | **DONE** |
| Structured portfolio tables | **TODO** |

---

## 7. Frontend — pages & UX (loading / completeness)

| Page / area | Loading | Completeness | Notes |
|-------------|---------|--------------|-------|
| **Home** | **PARTIAL** | **PARTIAL** | Indices / state OK; SystemStatus live `/ready` |
| **Active Strategy** | **DONE** | **PARTIAL** | Shared market state |
| **Confluence** | **DONE** | **PARTIAL** | LoadingBanner; needs MA/radar caches |
| **Stocks Option (Quant)** | **DONE** | **PARTIAL** | Job poll + merge retry + **buildup badges** + PCR triad + walls + ATM map |
| **VAT Scanner** | **DONE** | **PARTIAL** | LoadingBanner; basic scan |
| **Quant Dashboard** | **DONE** | **PARTIAL** | LoadingBanner; LIVE/DEGRADED/LOADING |
| **High Volume** | **DONE** | **PARTIAL** | Job poll + real `%` / current symbol |
| **Flow Radar** | **DONE** | **PARTIAL** | Job poll + real `%` / current symbol |
| **MA Crossover** | **DONE** | **PARTIAL** | Single process hub WS; real scan_progress |
| **MCP Trading** | **PARTIAL** | **PARTIAL** | Kill-switch banner |
| **Real-Time Alerts** | **DONE** | **PARTIAL** | Unique keys; single hub |
| **LoadingBanner** shared | **DONE** | — | Stocks, VAT, Quant, HV, Radar, Confluence |

### Known UI consistency issues

| Issue | Status |
|-------|--------|
| Bullish column but detail Neutral | **DONE** (`setup_side`) |
| Duplicate React keys (`intelligence`, `radar`) | **DONE** |
| Only ~20 stocks analyzed by default | **DONE** default full; job scans universe |
| Fake “Backend Active” | **DONE** live `/ready` |
| Fake LIVE on Quant | **PARTIAL** (state-aware) |
| Half page with no progress | **DONE** on Stocks Option job path |

---

## 8. What still makes scans feel “half done”

1. **Fyers rate limits** — full OC for ~180 names is many REST calls; system marks `partial` and supports **Retry failed only**.
2. **Jobs need Redis for durability** — with `REDIS_ENABLED=true` + Redis up, jobs survive restart (orphans → `interrupted`). Memory-only if Redis off/down.
3. **Radar / HV** not yet on the same job API (still one long HTTP).
4. **Multi-tab clients** — extra MA/alerts connections; close extra tabs.
5. **Market closed / bad symbols** — empty OC → errors, not setups.
6. **Grok 403** — news/confluence soft bias stays neutral.
7. **Jobs are not durable** — restart = lost job history (use Redis later).

---

## 9. Background scan job API

### Stocks Option
| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/market/stocks/scan/start` | Start job |
| `GET` | `/api/v1/market/stocks/scan/jobs/{job_id}` | Progress + `stocks[]` |
| `POST` | `/api/v1/market/stocks/scan/jobs/{job_id}/retry-failed` | Retry failed **and merge** into previous successes |
| `GET` | `/api/v1/market/stocks/scan/jobs` | List recent jobs |
| `GET` | `/api/v1/market/stocks/scan` | Legacy blocking |

### Radar
| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/radar/scan/start` | Start radar job |
| `GET` | `/api/v1/radar/scan/jobs/{job_id}` | Progress + `flagged[]` |
| `GET` | `/api/v1/radar/scan` | Legacy blocking |

### High Volume
| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/v1/market/high-volume-scan/start` | Start HV job |
| `GET` | `/api/v1/market/high-volume-scan/jobs/{job_id}` | Progress + `top_stocks` |
| `GET` | `/api/v1/market/high-volume-scan` | Legacy blocking |

**Key files**
- `backend/app/services/scan_jobs.py`
- `backend/app/routes/market_data.py`
- `backend/app/routes/option_flow_radar.py`
- `frontend/components/StockAnalysis.tsx`
- `frontend/components/OptionFlowRadar.tsx`
- `frontend/components/HighVolumeScanner.tsx`
- `frontend/lib/ma-crossover-hub.ts`
- `frontend/lib/api.ts`

**UI behaviour**
- Real `completion_pct` + `current_symbol` on Stocks / Radar / HV
- Stocks: merge-retry grows the grid
- MA: one WS per browser tab via hub

---

## 10. Recommended fix order (remaining)

### P0 — Production local desk
1. ~~Scan job API (Stocks / Radar / HV)~~ **DONE**  
2. ~~Retry-failed + merge~~ **DONE**  
3. ~~MA single WebSocket hub~~ **DONE**  
4. Valid Fyers token hygiene + docs  

### P1 — Strategy quality
5. Real **delivery / IV rank** sources  
6. VAT UI → advanced endpoint + confidence filters  
7. Radar `delivery_ratio` + 5-min vol baseline persistence  
8. Confluence: hard min 2 sources before ACTIONABLE (mostly done)  

### P2 — Platform
9. ~~Redis job store + L2 cache~~ **DONE** (optional; docker-compose redis)  
10. App-level API auth  
11. Structured MCP portfolio UI  
12. CI tests for `option_analytics` + scan job schema  
13. Multi-worker job *execution* resume (currently read-durable; worker stays process-local)  

### P3 — Polish
13. LoadingBanner on MA header strip / MCP  
14. Next.js routes per feature (not view-state only)  
15. Shared symbol context across tabs  

---

## 11. File map (this phase)

| Area | Key files |
|------|-----------|
| Scan jobs | `backend/app/services/scan_jobs.py` |
| Redis client | `backend/app/services/redis_client.py` |
| Docker Redis | `docker-compose.yml` |
| Stock scan API | `backend/app/routes/market_data.py` |
| Option math | `backend/app/services/option_analytics.py` |
| Intelligence | `backend/app/services/fno_intelligence.py` |
| Rate limit | `backend/app/services/rate_limiter.py` |
| Market cache | `backend/app/services/market_cache.py` |
| Signal bus | `backend/app/services/signal_bus.py` |
| Confluence | `backend/app/services/confluence.py` + `ConfluencePanel.tsx` |
| Stocks UI | `frontend/components/StockAnalysis.tsx` |
| Loading UI | `frontend/components/ui/LoadingBanner.tsx` |
| VAT / Quant / HV / Radar | respective `frontend/components/*` |
| API client | `frontend/lib/api.ts` |
| Alerts hub | `frontend/lib/alerts-hub.ts` |
| MA rotation | `backend/app/services/strategies/ma_crossover.py` |
| Symbols | `backend/app/services/fno_stocks.py` |

---

## 12. How to run / verify

```bash
# Backend (from backend/)
.\venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend (from frontend/)
npm run dev
```

**Checks**
1. `GET /api/v1/ready` → fyers ok/degraded, cache, rate limit  
2. `POST /api/v1/market/stocks/scan/start?limit=40&top_only=true&deep=true` → `{ job_id }`  
3. Poll `GET /api/v1/market/stocks/scan/jobs/{job_id}` → rising `completion_pct`, `current_symbol`, growing `stocks`  
4. UI **Stocks Option**: loading banner %, symbol under analysis, two columns, partial → **Retry failed only**  
5. VAT / Quant / HV / Radar / Confluence: LoadingBanner when fetching  
6. Close extra browser tabs for MA/alerts  

**Env**
```env
MCP_TRADING_ENABLED=false
GROK_API_KEY=          # optional; fix if news needed
FYERS_ACCESS_TOKEN=    # refresh daily
REDIS_ENABLED=true
REDIS_URL=redis://localhost:6379/0
REDIS_PREFIX=optiongreek
```

**Redis**
```bash
docker compose up -d redis   # from repo root
GET /api/v1/ready            # dependencies.redis = ok
```

---

## 13. Honest “full working” definition

| Claim | Honest status |
|-------|----------------|
| All strategies wired | **Yes (local)** — modules + confluence |
| All F&O always fully OC-analyzed in one click | **No guarantee** under Fyers limits — **jobs + partial + retry** is correct design |
| Dynamic loading tied to data | **Yes** on Stocks Option jobs; **banner + fetch flags** on major pages; HV still estimate % |
| Real-time everywhere | **No** — hybrid REST + limited WS |
| Institutional “truth” | **Heuristic** on OC/OI/volume |
| Unbiased bull/bear | **Yes by design** after quant vote + `setup_side` |

---

## 14. Minute / polish items still open (checklist)

- [x] Radar background job + progress
- [x] HV background job + real scanned count progress
- [x] Merge full scan + retry-failed into one grid
- [x] MA multi-tab: single shared WS hub
- [ ] VAT advanced scan UI fields (confidence filters, full analysis table)
- [ ] Persist last scan results across page navigation / refresh
- [ ] Empty OC during market closed → clearer “market closed / no chain” badges
- [ ] MCP portfolio structured UI
- [ ] API auth for LAN exposure
- [ ] Tests for setup_side + job schema
- [x] Redis durable jobs + L2 market cache + last radar scan
- [ ] Fix Grok key if news bias desired (**EXTERNAL**)
- [ ] Start Redis (Docker Desktop) on this machine when using durability

---

*Generated for review. Update statuses as items move TODO → DONE.*
