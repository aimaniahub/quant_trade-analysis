# PROJECT REPORT — OptionGreek Teardown & Flow Radar Rebuild

**Repo:** `quant_trade-analysis` (OptionGreek)  
**Date:** 29 August 2026  
**Status:** Diagnosis of the live tree + product decision + rebuild spec  
**Owner decision (this document):** delete the page zoo. Rebuild **one** product — Flow Radar — around **institutional option-chain anomalies**. Everything else is waste.

This file is the single source of truth going forward. Older docs (`architecture-plan.md`, `PHASE_1_README.md`, `PHASE_2_README.md`, `PHASE_3_README.md`, `docs/Option_Flow_Radar_System.md`, `docs/flow.md`, `docs/Option_Chain_Analyzer_Fix_Report.md`) describe I/O speed or partial scoring patches. They did **not** fix trade selection. Do not implement those plans as-is.

---

## 0. One-line verdict

The app can fetch F&O option chains. It cannot **choose a trade**.

Flow Radar, Stocks Option, Quant, VAT, 7/200, RSI, RSI Div, High Vol, Confluence, Live Trade Signal, and Home all load API data and each run a **different, incomplete** analysis. None of them:

- scores the **whole chain** (they collapse to one ATM-ish strike or a vote mash)
- uses **futures OI** as a first-class institutional input
- separates **structure** (PCR / walls / max pain / skew) from **flow** (OI + premium)
- flags **anomalies** (unusual size, wall shift, premium dislocation)
- defaults to **WAIT** when layers conflict
- produces a **stable** recommendation (side, strike, invalidation) that survives the next poll

Previous work spent months on harvest speed (serial → 4 workers, store-first, scheduler). That layer is usable. The **analysis layer is the failure**. Rebuild analysis. Delete the rest.

---

## 1. What this product was supposed to be

From `readme.md`, `docs/fnoanalysis.md`, and the owner's stated intent:

> In F&O stocks, price lies. Futures show intent. Options reveal manipulation.  
> The engine never predicts price. It interprets market behavior.  
> One question: **is this name setting up for a trade — or is it noise?**

The intended loop is:

```text
Fyers chain + futures + spot
        │
        ▼
  read the BOOK (who is writing / buying, where the walls are)
        │
        ▼
  flag ANOMALIES (size / location / disagreement that desks care about)
        │
        ▼
  if structure + flow + futures agree → one trade card
  else → WAIT / WATCH
```

What shipped instead is a **dashboard of scanners**. Ten entry buttons. Ten scoring systems. No desk.

---

## 2. Current system map (as of this tree)

### 2.1 Stack

| Layer | Tech |
| :--- | :--- |
| UI | Next.js 15, React 19, one shell `Dashboard.tsx`, no real routes |
| API | FastAPI, prefix `/api/v1` |
| Broker | Fyers API v3 REST + WebSocket |
| Book | In-process `symbol_store` + optional Redis |
| DB | None |

### 2.2 Boot path (`backend/app/main.py`)

On start the process:

1. Optional Redis
2. Candle aggregator + Fyers data socket subscriber
3. **RadarScheduler** — full 187-name harvest every **180s** while open
4. **Spot stream** — WS LTP into the symbol store
5. History sweeper — idle until first harvest ends
6. Legacy MA crossover auto-scan is **disabled** (good)

So there is already **one intended writer** (Radar harvest). Other pages still exist as separate product surfaces and, in several cases, still start their own scans.

### 2.3 Universe

| Set | Count | Source |
| :--- | ---: | :--- |
| F&O stocks | 184 | `backend/app/services/fno_stocks.py` |
| F&O indices | 3 (NIFTY, BANKNIFTY, FINNIFTY) | same |
| TOP tier | 31 stocks + 3 indices = 34 | same |
| Watchlist after invalid filter | **187** | TATAMOTORS / HDFC / NIFTYFIN-INDEX dropped |

Fyers budget that actually binds:

| Window | Cap | Meaning |
| :--- | ---: | :--- |
| Per second | 10 | burst ceiling |
| Per minute | **200** | binding constraint |
| Option chain | **1 underlying / request** | this **is** the harvest |
| Quotes | 50 symbols / request | cheap |
| History | 1 symbol × 1 resolution | secondary |
| WebSocket | LTP/OHLC/volume, **not** full OI chain | spots only |

### 2.4 UI surface today

One page. Ten views. Buttons in `frontend/components/Dashboard.tsx`:

| View | Component | Lines | What it claims |
| :--- | :--- | ---: | :--- |
| Home | MarketState + Indices + NIFTY chain + Confluence + Alerts | — | market overview |
| Quant Dashboard | `QuantDashboard.tsx` | 207 | live signal + greeks heatmap + nifty sentiment |
| Stocks Option | `StockAnalysis.tsx` | 1487 | full-universe OC scan + BUY/WAIT columns |
| VAT Scanner | `VATScanner.tsx` | 355 | Value Adjustment Theory |
| Trading | `MCPTradingPanel.tsx` | 479 | MCP / Fyers orders |
| 7/200 Cross | `MA7200Scanner.tsx` | 923 | 15m MA cross + OC confirm |
| RSI Div | `RSIDivergenceScanner.tsx` | 664 | RSI divergence |
| Flow Radar | `OptionFlowRadar.tsx` | **3216** | process / flow / tape |
| High Vol | `HighVolumeScanner.tsx` | 644 | relative volume + bulk OC |
| RSI (orphan) | `RSIScanner.tsx` | 479 | RSI zones — **no nav button**, still mounted by view `'rsi'` |

Home **unmounts** when you leave (good, after a recent fix). Radar stays mounted via `keepRadar` so Back does not wipe the board.

---

## 3. Why Flow Radar fails to choose trades

This is the core of the project. Speed is no longer the main bug.

### 3.1 It does not analyse a chain. It picks one strike.

`OptionFlowRadarService._process_option_chain` (`option_flow_radar.py`):

1. Walks CE and PE near ATM (≤ 7%).
2. Drops a strike unless OI% **or** volume **or** premium move clears a floor.
3. Classifies each surviving leg with the 8-cell CE/PE matrix.
4. Sorts by `abs(OI%) * log(volume) * ATM-boost`.
5. Fully scores **top 4** only.
6. Returns **`scored[0]`** — one contract for the whole stock.

An institution does not trade “the highest LIS strike.” They sit on **walls, clusters, and futures**. A name with:

- put wall at 500, call wall at 540
- PCR 0.62 (call-writing ceiling)
- futures short buildup
- one 510 CE with +12% OI and a volume pop

…currently becomes **BUY 510 CE** if that strike wins the LIS sort. That is the opposite of a desk read.

### 3.2 Harvest-path scoring is fake context

Scan path (`scan_all` → `_scan_one`):

```text
fetch_vol_history = False
enrich_underlying = False
attach_heavy      = False
```

`_underlying_from_store` then invents:

| Field | Harvest value | What it should be |
| :--- | :--- | :--- |
| `vwap` | **spot LTP** | session VWAP from 15m / 5m |
| `ema20` | **spot LTP** | EMA20 of stored 15m |
| `vwap_dev_pct` | **0.0** | (spot − VWAP) / VWAP |
| `above_ema20` | **`change_pct >= 0`** | real EMA side |
| `delivery_ratio` | **hardcoded `1.0`** in `build_scored_contract` | not even available from Fyers chain |
| `vol_spike_ratio` | chain-median of near-ATM peers **including itself** | 3-day own-contract history (skipped) |

The light REST path is worse. It constructs EMA so LTP is **always** on the “correct” side of the day:

```text
ema20 = ltp * (0.998 if day_change >= 0 else 1.002)
vwap_dev_pct = 0.0
above_ema20 = day_change >= 0
```

If even store spot is missing, harvest synthesizes `above_ema20: True` always.

`_write_derived` **does** compute real 15m VWAP / EMA20 — **after** the history sweeper, which starts when harvest **finishes**. Scoring never sees it. `get_symbol_flow` can have `derived.vwap` and still write `vwap_dev_pct: 0.0`.

LIS then awards:

- up to **15 points** for “near VWAP” — always maxed, because deviation is 0
- **10 points** EMA trigger — true whenever the stock is green on the day
- **2.5–5 points** delivery — always full (`delivery_ratio=1.0` → `min(1/2,1)*5 = 2.5`)

So ~27–30 of 100 LIS points are **noise**. Remaining spread is mostly `|OI%|` and premium — the **same two numbers** that already labelled the signal. Grades A / A+ / B / C are computed on that. The board ranks fiction.

### 3.3 Hard filters sit on a knife-edge

From `radar_signal_engine.py`:

| Filter | Value | Failure mode |
| :--- | ---: | :--- |
| ATM distance | 7% | 7.1% is invisible; ATM itself walks as spot ticks |
| OI change | 8% | 7.9% → Neutral, 8.1% → Fresh Buying. Fyers `oichp` is often 0; we reconstruct, still jumpy |
| Premium change | 1.5% | same knife-edge on `chg_pct` |
| Volume | 150 contracts | tiny names pass; liquid names need much more |
| Vol spike | 1.5× | vs **peer median of the same snapshot**, so a uniformly busy chain looks “normal” |
| Greek quality | 8 / 20 | Black-Scholes greeks computed locally from IV; filter, not signal — but they still drive grade |

Result (already documented in `docs/flow.md`): the “best trade” flips every snapshot. That file was marked *research, not implemented*. Idea-book hysteresis was added later and is **skipped on harvest** (`attach_heavy=False`). The listing the user stares at is still the snapshot election.

### 3.4 Six scoring numbers, no decision

A flagged row can carry all of:

| Number | Producer | Used for |
| :--- | :--- | :--- |
| `lis` 0–100 | `compute_lis_v2` | rank + grade gates |
| `greek_quality` 0–20 | `compute_greek_quality_score` | grade downgrade |
| `unusual_score` 0–100 | `compute_unusual_score` | Alert Box |
| `composite_score` | `lis*0.55 + gq*2 + unusual*0.25 + 10` | pick winner strike |
| `desk_score` 0–100 | `rsi_desk.weight_radar_row` | **re-sorts** the board with RSI |
| `process_composite` | idea engine | lock — not on harvest path |

Then `weight_radar_row` stacks LIS + RSI15 + OC permission + 4H MTF into `desk_score` **without changing grade**. The UI can rank by a number the signal engine never heard of.

This is circular: premium sign → direction → momentum (same premium) → LIS → composite (LIS again) → desk_score (LIS again) → idea composite (LIS again). Independent information is not being added.

A+ is almost unreachable on harvest (needs unusual **and** LIS≥60 **and** greeks **and** strong_flow). **Flagged = A/A+ only.** Most names land C, or B via the `LIS≥35` loophole. The board “chooses” an empty flagged list. `desk_score` cannot promote a C. Scheduler bus further drops below `MIN_LIS_PUBLISH=65`.

There is no single function that answers: **trade it, or not.**

### 3.5 “Institutional” on the radar is theatre

`compute_unusual_score` is the closest thing to anomaly detection. It adds points for:

- OI % buckets (15 / 25 / 40)
- volume multiple (2 / 3 / 5)
- absolute OI added (15k / 50k / 200k)
- premium + IV
- slightly-OTM size
- adjacent-strike cluster

Problems:

1. **Not chain-relative by liquidity.** 50k OI on NIFTY is noise. 50k OI on a mid-cap is an event. Floor is global.
2. **Not compared to the name’s own history.** First snapshot of the day has no baseline.
3. **Does not look at walls, PCR, max pain, skew, or futures.**
4. Alert Box is a **parallel list**, not a gate on trade cards. A name can be A+ on fake LIS and miss the Alert Box, or be Alert Box with grade C.
5. `unusual_flags` then appends `"Dir BULLISH"` and `"Grade A"` — labels, not anomalies.

### 3.6 Process-trade lock never runs on the scan that fills the board

`_attach_process_trade` is the only path that builds:

- levels (pivots, Camarilla, CPR, VWAP, OR, OI walls)
- MTF Daily / 4H / 1H / 15m
- OI clusters → entry / stop / target
- IdeaBook ingest (hysteresis, lock)

Harvest calls `_process_option_chain(..., attach_heavy=False)`. Futures and rich candles are skipped. Idea ingest still runs but on a **starved** snapshot (VWAP = LTP, empty 5m). Promotion needs composite ≥ 70, location ≥ 4, same direction for 180s — with dummy inputs this either never promotes, or promotes garbage.

Row click (`GET /radar/flow/{symbol}`) is the path that can attach heavy. So the **board** is a LIS beauty contest; the **card** after a click is a different engine. The user cannot trust either.

### 3.7 CE/PE matrix is correct and insufficient

`classify_signal` implements the standard 8-cell matrix. That part is fine:

| | Premium ↑ | Premium ↓ |
| :--- | :--- | :--- |
| **CE OI ↑** | Fresh Call Buying (bull) | Call Writing (bear) |
| **CE OI ↓** | Call Short Covering (exhaustion) | Call Long Unwinding (bear) |
| **PE OI ↑** | Fresh Put Buying (bear) | Put Writing (bull) |
| **PE OI ↓** | Put Short Covering (exhaustion) | Put Long Unwinding (bull) |

This labels **one leg**. It is not a chain read. Exhaustion is not hard-vetoed from A-grade (only “strong_flow” prefers buying/writing). Neutral legs get resurrected as `"Tape / OI build"` if volume ≥ 150 or OI ≥ 50k — which re-injects noise the matrix just rejected.

### 3.8 Structural fallback manufactures a candidate when there is no flow

If nothing passes filters, `_structural_candidate` still feeds `build_scored_contract` so the tape is not empty. Empty should mean **empty**. Filling the board with a structural dummy is why “something always shows” and nothing is tradable.

---

## 4. The analysis zoo (competing engines)

There is not one option-chain analyzer. There are **at least seven**, and they disagree.

```text
                    Fyers optionchain
                            │
          ┌────────┬────────┼────────┬────────┬────────┐
          ▼        ▼        ▼        ▼        ▼        ▼
     Radar v3   option_    fno_     HV rec   VAT     7/200
     LIS/grade  analytics  intel    live     scan    desk
          │        │        │        │        │        │
          │        └─ deep_analyze_chain ─┘   │        │
          │        └─ desk_decision ──────┘   │        │
          ▼                                   ▼        ▼
     Flow Radar UI                      other pages
          │
          └─ rsi_desk.weight_radar_row  (8th score)
          └─ confluence votes MA + radar + news + NIFTY intel
```

### 4.1 Engine A — Radar signal (`radar_signal_engine.py`, 655 lines)

**Used by:** Flow Radar harvest and row click.  
**Inputs:** one option leg + dummy underlying.  
**Output:** LIS, grade, unusual, composite.  
**Institutional?** No. No PCR, walls, max pain, skew, futures.  
**Verdict:** keep the **CE/PE matrix function**. Throw away LIS / layers / grades as the decision system.

### 4.2 Engine B — Mathematical pack (`option_analytics.py`, 996 lines)

This is the **best unfinished work** in the repo.

`deep_analyze_chain` actually computes what a desk uses:

| Block | Function | Meaning |
| :--- | :--- | :--- |
| PCR suite | `compute_professional_pcr` | OI PCR, volume PCR, ATM PCR, band PCR, regime label |
| Max pain | `compute_max_pain` | pin magnet |
| ATM straddle | `compute_atm_straddle` | expected move / premium regime |
| IV structure | `compute_iv_structure` | skew |
| Greeks walls | `compute_greeks_walls` | gamma wall, pin risk |
| Structure walls | `compute_structure_walls` | call wall / put wall |
| Buildups | `analyze_chain_buildups` + `classify_buildup` | Long/Short/SC/LU per strike and ATM band |
| Dislocation | `compute_premium_dislocation` | rich/cheap vs model |
| Magnets | `compute_oi_magnets` | OI concentration |

Then `composite_quant_score` **votes** these into a 0–100 and a BULLISH/BEARISH/NEUTRAL. The vote still over-weights buildup (the exact bug `docs/Option_Chain_Analyzer_Fix_Report.md` recorded on LICHSGFIN). `desk_decision.py` was written to harden that (HTF → PCR → buildup → gamma → skew → 15m, default WAIT). That hardening is used by **Stocks Option / fno_intelligence**, **not by Flow Radar**.

**Verdict:** keep the **pure calculators**. Kill `composite_quant_score` as a trade decider. Radar must **flag** the raw structure, not average it into a score.

### 4.3 Engine C — F&O Intelligence (`fno_intelligence.py`, 952 lines)

Wraps Engine B, adds:

- IST time windows that force **NO-TRADE** 9:15–10:30 and last 10 minutes
- `_analyze_institutional_flow`: volume/OI > 1.5 **or** round-strike volume > 50k → “CALL_ACCUMULATION”. Intent score += 10 per hit, cap 100. Round number ≠ institution.
- `_classify_market_state`: INTENT if that toy score > 40
- `tradable` if state ∈ {TREND, INTENT, ADJUSTMENT} — **a clock and a volume/OI ratio can mark a name tradable**
- strike guidance “BUY ONLY”

Wired to `/options/analysis`, `/options/adjustments`, `/market/stocks/scan`, live-trade-signal.

**Smoking gun:** `/options/analysis/{symbol}` returns `"anomalies": []` **hardcoded empty** (`routes/option_chain.py`). The API the UI would use to flag the chain **does not flag anything**.

**Verdict:** delete as a product engine. Steal nothing except the time-window *warning* (not a hard kill of analysis).

### 4.4 Engine D — High-volume live rec (`high_volume_scanner.py`)

`_generate_trade_recommendation` copies intelligence `strike_guidance`, then sets stop = OI support, target = OI resistance. Used by Quant’s `LiveTradeSignal`. Third independent rec.

If a process idea is ACTIVE, this route **overrides** itself with the idea book. Two engines, last-write-wins.

### 4.5 Engine E — VAT (`strategies/vat.py`)

Separate philosophy (premium dislocation / value adjustment). Own scan, own Fyers path historically. Not wired into Radar decisions. A research toy.

### 4.6 Engine F — 7/200 (`ma7200_scanner.py` + `ma7200_desk.py`)

MA cross first, option chain as confirmation. Opposite of the product rule (“moving averages only create context”). Own job system, own page.

### 4.7 Engine G — RSI / RSI Div (`rsi_desk.py` 1213 lines, `rsi_divergence.py`)

Oscillator scanners. `weight_radar_row` injects RSI into Radar ranking. This is how technicals **contaminate** the one page that should be flow-first.

### 4.8 Engine H — Confluence (`confluence.py`)

Counts agreement between MA crossovers (disabled engine), last radar row, signal bus, optional Grok news, and a **fresh NIFTY intelligence snapshot**. “2 sources agree → ACTIONABLE.” Voting broken scanners does not create a trade.

---

## 5. Dummy, missing, and wrong parameters

### 5.1 Present in code, meaningless on the harvest that users see

| Parameter | Code | Why it is fake |
| :--- | :--- | :--- |
| VWAP deviation | LIS 15 pts | VWAP := LTP |
| EMA20 side | LIS 10 pts | `above_ema20 := day change ≥ 0` |
| Delivery ratio | LIS 5 pts | hardcoded `1.0` — Fyers chain has no delivery |
| 3-day volume spike | unusual + layer 2 | skipped on harvest; peer-median used |
| Greek quality | grade gate | local BS from IV; harvest still uses it |
| `desk_score` | re-rank | RSI stacked after the fact |
| Time-window NO-TRADE | intelligence | opening hour is when walls form |
| Round-strike “institutional” | intelligence | every Nifty strike is a round number |
| `anomalies: []` | options analysis API | the feature was never wired |

### 5.2 Actually matter for NSE F&O — **mostly unused by Radar**

These exist in `option_analytics.py` / `levels.py` / Fyers payloads and are **not** the Radar decision:

| Parameter | Why a desk cares | Where it lives today |
| :--- | :--- | :--- |
| **Futures price vs spot (basis)** | who is paying up; lead/lag | `levels.get_futures`, not in LIS |
| **Futures OI + price** | long/short buildup of real money | same, harvest `attach_heavy=False` |
| **OI PCR + volume PCR + ATM PCR** | writing ceiling / floor | `compute_professional_pcr`, Stocks Option only |
| **Call wall / put wall** | where size sits; magnet / cap | `compute_structure_walls` |
| **Gamma wall / pin risk** | expiry mechanical pressure | `compute_greeks_walls` |
| **Max pain vs spot** | pin; not a direction by itself | `compute_max_pain` |
| **IV skew** | crash demand vs call demand; **flat = zero edge** | `compute_iv_structure` |
| **ATM straddle Δ** | premium expanding or crushed | `compute_atm_straddle` |
| **Absolute OI added, liquidity-scaled** | real size, not 8% on 2k OI | unusual_score, unscaled |
| **Adjacent-strike cluster** | coordinated book | `count_cluster_hits`, weak |
| **CE vs PE band buildup** | both sides shouting | `analyze_chain_buildups`, not Radar |
| **Wall migration vs last snapshot** | institutions moving the goalposts | **not implemented** |
| **Premium dislocation** | rich/cheap vs peers | `compute_premium_dislocation`, unused by Radar |
| **DTE / weekly vs monthly** | theta and pin | expiry string only |
| **Index alignment** | stock long vs NIFTY crumbling | missing |
| **Persistence across harvests** | idea lock | skipped on harvest |

### 5.3 Parameters that should never decide a trade

- RSI / RSI divergence
- 7/200 MA cross as a primary
- VAT narrative as a primary
- News Grok bias as a vote
- Composite 0–100 “quant_score”
- LIS 0–100
- Grade letters A+/A/B/C
- Confluence source count
- Opening-hour blanket NO-TRADE

Technicals (VWAP, 4H) are **gates and location**, not generators.

---

## 6. Page-by-page: what loads, what it is worth

| Page | Poll / trigger | Fyers risk | Analysis quality | Decision |
| :--- | :--- | :--- | :--- | :--- |
| **Home** | state 45s, chain 45s, indices 45s, confluence 60s, ready 20s | store-first now; still duplicate NIFTY reads | Market state is intelligence-lite; confluence is a vote | **Kill as product.** Replace with Radar board shell (auth + status + indices from store) |
| **Flow Radar** | `/radar/last` 15s, ideas 30s, job 1.5s, row click `/radar/flow` | harvest writer; click can still cost REST if store cold | Broken decision, usable I/O | **Keep shell. Replace engine and UI model** |
| **Stocks Option** | own `/market/stocks/scan/start` full 187 CPU re-score | store-only now; **second desk on the same book** | Engine B+C, still score-mash, WAIT forced under Bullish so the grid is not empty (`_apply_setup_side`) | **Kill.** Same chains as Radar, different recs |
| **Quant Dashboard** | HV scan on mount + live-signal + greeks heatmap + nifty sentiment | store-only; duplicate NIFTY | Duplicate rec of the idea book | **Kill** |
| **VAT** | `/strategies/vat/scan` | store chain + 15m | Unrelated theory | **Kill** |
| **7/200** | own scan job | store 15m + OC | MA-first | **Kill** |
| **RSI / RSI Div** | `/strategies/rsi/*` | store history | Oscillator | **Kill** |
| **High Vol** | `/market/high-volume-scan` | store 15m; bulk OC is a third intel pass | Volume rank ≠ institutional | **Kill as page.** Volume spike becomes a Radar anomaly type |
| **Trading / MCP** | tools / orders | not market-data | Execution rail | **Keep later**, not in v1 rebuild. Order placement already kill-switched (`mcp_trading_enabled=false`) |
| **Confluence panel** | 60s | NIFTY intel | Vote of broken sources | **Kill** |
| **Greeks heatmap** | on Quant | extra OC if width mismatch | Visual only | **Fold into Radar chain detail** |
| **Live Trade Signal** | Quant | extra OC | Engine D | **Kill** |
| **Nifty sentiment** | Quant | VIX + up to 3× NIFTY OC + 50 quotes (historically) | Index regime is useful | **Fold into Radar as index context**, store-only |

### 6.1 Duplicate harvests still in the tree

Phase 1–3 **did** make Home / Quant / VAT / HV / 7/200 / RSI / Stocks Option **store readers**. They no longer independently walk Fyers when `FYERS_READER_ESCAPE=false`. They are still **waste as product**: they re-score the same book and emit conflicting recs.

Remaining **real** Fyers writers / hatches:

| Job | Route | Purpose |
| :--- | :--- | :--- |
| Radar scheduler | lifespan every 180s | **the** harvest — keep |
| Radar manual Scan | `POST /radar/scan/start` | nudge the same job — keep as button |
| **Custom scan hatch** | `POST /radar/scan` | still calls `scan_all` **without** `ensure_pass` when idle — **delete** |
| Legacy GET scan | `GET /radar/scan` | also nudges harvest — **delete** |
| History sweeper | after first harvest | keep, leftover RPM only |
| Confluence “trigger radar” | `POST /confluence/radar/scan` | **delete** |
| 5m candles / backtest | `/radar/candles`, `/radar/backtest` | 5m is **not** in the book → `store_miss`; would storm REST if escape is on — **delete** until engine exists |
| Stocks / HV / 7/200 / VAT / RSI jobs | their `/start` routes | store-only **CPU** jobs; **delete** as product, not as quota thieves |

One writer. One book. One reader UI.

### 6.2 Frontend waste

- `OptionFlowRadar.tsx` is **3216 lines** — process tab, flow tab, tape, job polling, session cache, backtest, levels, ideas. It is a second application.
- `StockAnalysis.tsx` is **1487 lines** of a parallel scanner.
- `lib/api.ts` exposes every dead engine.
- No Next.js routes; all views are flags. Fine for a single-page desk; not an excuse for ten products.

---

## 7. API surface (keep vs delete)

### 7.1 Keep (data plane + auth + rebuilt radar)

| Endpoint | Role |
| :--- | :--- |
| `GET /health`, `GET /ready` | process health |
| `/auth/*` | Fyers login / TOTP / token |
| `GET /market/store/status` | book freshness |
| `GET /market/indices` | store-only index quotes |
| `GET /market/spot/{symbol}` | store-only |
| `GET /options/chain/{symbol}` | store-only chain for the Radar detail pane |
| `GET /radar/last` | live board |
| `POST /radar/scan/start` | nudge the one harvest |
| `GET /radar/scan/jobs/{id}` | progress |
| `GET /radar/watchlist` | universe |
| `WS /ws/market` | LTP fan-out (optional) |

Rebuild (new contract, same prefix is fine):

| Endpoint | Role |
| :--- | :--- |
| `GET /radar/board` | anomaly-flagged names (replaces flagged/watch/alert_box soup) |
| `GET /radar/symbol/{symbol}` | full chain flags + structure + optional trade card |
| `GET /radar/ideas` | locked trades only (if we keep hysteresis) |

### 7.2 Delete or freeze (no UI)

Everything under:

- `/market/stocks/scan*`
- `/market/high-volume-scan*`
- `/market/bulk-oc-analysis`
- `/market/live-trade-signal/*`
- `/market/greeks-heatmap/*`
- `/market/nifty-sentiment`
- `/market/news-bias`
- `/confluence*`
- `/strategies/vat/*`
- `/strategies/ma7200/*`
- `/strategies/rsi/*`
- `/ma-crossover/*`
- `/radar/backtest` (until the new engine exists)
- `/radar/levels` as a standalone (fold into symbol detail)
- `/mcp/*` for v1 product (keep code for later)

MCP and orders stay in the repo; they are not the product.

---

## 8. What previous docs got wrong

| Doc | What it solved | What it missed |
| :--- | :--- | :--- |
| `architecture-plan.md` | Serial harvest, false 429s, hidden Home polls, listing waits for 187/187 | Explicitly said **do not touch the signal engine** |
| `PHASE_1/2/3_README.md` | Single writer, 4 workers, store-first, WS spots, history sweeper | Same. “Existing scoring untouched” |
| `docs/Option_Flow_Radar_System.md` | Describes the intended process-trade stack | Documents a design the harvest path does not run |
| `docs/flow.md` | Correctly named flicker / no memory | Marked not implemented; idea book is still off the listing path |
| `docs/Option_Chain_Analyzer_Fix_Report.md` | Correct priority (HTF → PCR → buildup → gamma → skew → WAIT) | Applied to Stocks Option, not Radar; still a **score**, not an anomaly flag |
| Spec v3 | Fixed CE/PE matrix and put-aware momentum | Then buried it under LIS + 6 layers + grades |

Phase 1–3 **data plane** is the one thing to keep:

- Market Gateway / `fyers_market` store-first
- Symbol store (chain, spot, history, futures)
- Rate limiter with real 429s only
- 4-worker chain harvest, TOP-34 first
- RadarScheduler as sole writer
- Spot WebSocket
- History sweeper after chains
- Incremental board publish

Do not rip the book to punish the scorer.

---

## 9. Target product (locked)

### 9.1 One sentence

**Flow Radar harvests every F&O chain on a budget, flags institutional anomalies on the chain, and only then may emit one trade card with an invalidation.**

### 9.2 Non-negotiable laws

1. **One writer.** Only the harvest may call Fyers market REST (plus WS ticks).
2. **One book.** Every UI read is store-only. Empty book → “waiting for harvest”, never a surprise REST walk.
3. **One analyzer.** One function: `analyze_chain(snapshot, prev_snapshot) → ChainReport`.
4. **Anomaly first, score never.** No LIS, no A+, no desk_score, no confluence votes.
5. **WAIT is a first-class output.** Conflict, missing futures, flat skew + no size, or one-print wonders → no trade card.
6. **Whole chain, not one strike.** The name is the unit. Strikes are evidence.
7. **Futures are mandatory context** when the quote exists; if missing, cap at WATCH.
8. **Technicals do not generate.** VWAP / 4H / Daily may **block** or **locate**, never create a bullish from a bearish book.
9. **Persistence.** A TRADEABLE flag must repeat on the next harvest (or hold 3 minutes) before it is a card. Scan ≠ decide.
10. **Other pages do not exist** in v1.

### 9.3 What the user sees (v1)

```text
┌─────────────────────────────────────────────────────────────┐
│  OptionGreek · Flow Radar     AUTH  STORE  HARVEST 09:41    │
│  NIFTY 24820  BN 51210  VIX 13.4     Scan   Last 42s ago    │
├──────────────┬──────────────────────────────────────────────┤
│ FILTERS      │  CHAIN DETAIL (selected name)                │
│ TRADEABLE 12 │  Structure: PCR 0.68 CEILING · Put 24700     │
│ WATCH 31     │               Call 25200 · γ-wall 24800      │
│ FLAGGED 48   │  Futures: discount, OI↑, SHORT BUILDUP       │
│              │  Anomalies:                                  │
│ RELIANCE  ●  │   • 2480 PE +1.2L OI (3.4× chain median)     │
│ TCS       ●  │   • Call wall migrated 2500 → 2520           │
│ SBIN      ○  │   • ATM straddle −8% (crush)                 │
│ ...          │  Bias: BEARISH  (writing + futures agree)    │
│              │  Card: WAIT — crush + ceiling, no trigger    │
│              │  or TRADE: BUY 2480 PE, invalidation 2492    │
└──────────────┴──────────────────────────────────────────────┘
```

Three buckets only:

| Bucket | Meaning | Trade card? |
| :--- | :--- | :--- |
| **TRADEABLE** | structure + flow + futures agree, anomaly is real, persisted | Yes |
| **WATCH** | anomaly exists, layers incomplete or young | No |
| **QUIET** | scanned, nothing unusual | No (hidden by default) |

No Alert Box vs Normal Radar vs Process vs Tape vs Ideas as separate religions.

---

## 10. Rebuild spec — Chain Anomaly Engine

This replaces `radar_signal_engine.py` + harvest scoring + `fno_intelligence` decision + `composite_quant_score` + `desk_decision` as the product brain.

### 10.1 Inputs (all from the symbol book)

Per symbol, per harvest:

```text
chain[]          strike, CE/PE: ltp, chg%, oi, prev_oi, oich, volume, iv, bid/ask if any
spot             ltp, day_change_pct
futures          ltp, oi, oi_change, volume, basis = fut − spot   (may be missing)
history.15       for real VWAP / EMA only (gate, not score)
history.D        for HTF gate only
prev_report      last harvest’s walls / PCR / max pain / flags   (memory)
index_ctx        NIFTY/BANKNIFTY bias from the same book
vix              level + day change
expiry           nearest DTE
```

No RSI. No 7/200. No news. No delivery ratio.

### 10.2 Layer 0 — Quality of the print (hard)

Drop the name to QUIET (do not guess) if:

- chain rows < 6 or spot ≤ 0
- nearest expiry missing
- both total CE volume and PE volume below a **liquidity floor**  
  - index: 1,00,000 contracts combined  
  - stock: 10,000 combined (tune per bucket: nifty-50 vs rest)
- harvest age > 3 minutes and market open → stale badge, do not invent

### 10.3 Layer 1 — Structure (the book)

Compute once per chain (reuse existing pure functions from `option_analytics.py`):

| Field | Rule of interpretation |
| :--- | :--- |
| `oi_pcr` | **< 0.70** Call-writing ceiling (bearish pressure / cap). **> 1.25** Put-writing floor (bullish cushion). 0.85–1.15 balanced |
| `vol_pcr` | same-day aggression; **< 0.45** aggressive call activity (often into a ceiling); **> 1.6** aggressive put activity |
| `call_wall` / `put_wall` | max CE OI / max PE OI strikes |
| `spot_vs_walls` | below put wall = cushion nearby; above call wall = breakout or chase |
| `gamma_wall` | if `|spot − γ| / spot < 0.4%` near expiry → pin risk, **no directional card** |
| `max_pain` | context only; never a vote by itself |
| `iv_skew` | Put IV − Call IV. **\|skew\| < 2 → zero vol edge** (do not bonus). Skew > 3.5 crash demand; < −2 call demand |
| `straddle_chg_pct` | **< −6%** crush (writing / vol crush). **> +6%** expansion (buying / event) |
| `atm_band_buildup` | 4-state on ATM ± 2 strikes, CE and PE separately |

**Structure bias** (not a trade):

```text
if oi_pcr < 0.70 and call_wall within 1.5% above spot → STRUCTURE_BEARISH (ceiling)
if oi_pcr > 1.25 and put_wall within 1.5% below spot  → STRUCTURE_BULLISH (floor)
if gamma pin                                          → STRUCTURE_PIN
else                                                  → STRUCTURE_MIXED
```

### 10.4 Layer 2 — Futures (intent)

Canonical futures matrix (already in `docs/fnoanalysis.md`, never used as a Radar gate):

| Futures price | Futures OI | Label |
| :--- | :--- | :--- |
| ↑ | ↑ | LONG_BUILDUP |
| ↓ | ↑ | SHORT_BUILDUP |
| ↑ | ↓ | SHORT_COVERING (fade risk) |
| ↓ | ↓ | LONG_UNWINDING |
| flat | ↑ | TRAPPED |
| flat | ↓ | EXIT |

**Rules:**

- SHORT_COVERING and LONG_UNWINDING **cannot** produce TRADEABLE. Max WATCH.
- If futures missing → cap at WATCH even when options scream.
- Basis: large contango + PE buying = hedge, not panic; large backwardation + CE writing = not a breakout.

### 10.5 Layer 3 — Strike anomalies (flag the chain)

For every CE and PE in the harvested width (14 stocks / 20 indices):

**A. Size anomaly (absolute, then relative)**

```text
oi_added = oi - prev_oi   (or reconstruct from oich)
vol      = session volume

unusual_size IF
    abs(oi_added) >= size_floor(symbol)          # liquidity scaled
    AND abs(oi_added) >= 0.08 * prev_oi          # 8% still useful as relative
    AND volume >= vol_floor(symbol)
```

Suggested floors (v1, tunable, **not** global 50k):

| Bucket | OI-add floor | Volume floor |
| :--- | ---: | ---: |
| Index (NIFTY/BN/FN) | 2,00,000 | 50,000 |
| Heavy F&O (TOP 31) | 40,000 | 8,000 |
| Rest | 15,000 | 3,000 |

**B. Location anomaly**

- ATM ± 2% with size → expected, weaker flag unless also vol-spike vs **own** prior snapshot
- **2–6% OTM** with size + vol → classic institutional (hedge / write). Strong flag
- > 7% OTM with size → far-OTM lottery or hedge; flag as WATCH, not TRADEABLE

**C. Flow label** (keep the 8-cell matrix, apply to the **anomalous** strike only)

Buying vs writing vs exhaustion as today. Exhaustion = WATCH at best.

**D. Cluster**

≥ 3 adjacent strikes, same side, same direction, each with meaningful OI-add → `CLUSTER` flag. This is the actual “big player” signature, not round numbers.

**E. Wall migration** (needs `prev_report`)

Call wall or put wall moved ≥ 1 strike step since last harvest → `WALL_SHIFT`. Institutions relocating the cap/floor.

**F. Volume vs prior snapshot of the **same** contract**

If we stored last chain, `vol_now / max(vol_then, 1)` ≥ 3 and OI rising → real spike. Peer-median-of-now is a fallback only.

### 10.6 Layer 4 — Agreement → bias

```text
flow_bias     from anomalous strikes (net CE-bull vs PE-bear vs writing)
structure_bias from Layer 1
futures_bias  from Layer 2
htf_bias      Daily + 4H agree? else HTF_MIXED  (gate only)

if flow == structure == futures (and HTF not opposite):
    chain_bias = that side
    grade = TRADEABLE if (cluster OR wall_shift OR otm_size) and not exhaustion
          else WATCH
elif any two agree and third missing/mixed:
    chain_bias = the two
    grade = WATCH
elif flow opposes structure:
    chain_bias = CONFLICTED
    grade = WATCH or QUIET
    NO CARD
else:
    QUIET
```

**HTF opposite the options+futures agreement → cap at WATCH.** Never flip the side to match the MA.

**Index opposite a stock TRADEABLE → downgrade to WATCH** (stock long, NIFTY structure bearish).

### 10.7 Layer 5 — Trade card (only TRADEABLE)

One card per name.

| Field | Rule |
| :--- | :--- |
| `side` | LONG if chain_bias BULLISH, SHORT if BEARISH |
| `instrument` | BUY CE for long, BUY PE for short. **No naked writing in v1** (margin/assignment out of scope) |
| `strike` | the anomalous strike **in the direction**, preferring: cluster center, else max `oi_added` inside ATM 5%, else ATM |
| `entry` | not “market”; location: VWAP reclaim/reject **or** bounce off put/call wall, from stored 15m. If no location, WATCH not TRADEABLE |
| `stop` | beyond the opposing wall or beyond VWAP by 0.6× ATR(15m), whichever is tighter |
| `target` | next wall / max pain / 1.2–1.5R. If R:R < 1.0 → no card |
| `invalidation` | flow flip (writing appears on our side) **or** wall break **or** futures OI reverse |
| `thesis` | one sentence: structure + futures + the anomaly. No emoji grades |

Hysteresis:

- Promote to TRADEABLE only if the same `chain_bias` on **2 consecutive harvests** (or 3 minutes).
- Kill the card if invalidation hits, or grade drops, or two harvests of CONFLICTED.
- Do not change strike every print: lock strike until `|spot − strike| / spot > 8%` or invalidation.

### 10.8 What we explicitly will not score

- 0–100 LIS / quant / desk / unusual composite as a rank key
- Greek quality 0–20 as a grade (delta still used as **reject** if < 0.15 on a directional buy)
- Delivery, RSI, 7/200, VAT, news
- “Smart Money Accum.” as a trade
- Structural fallback candidates to fill an empty tape

Greeks: keep as **risk footnotes** on the detail pane (theta, IV rich). They do not create flags.

### 10.9 Output contract (`ChainReport`)

```json
{
  "symbol": "NSE:RELIANCE-EQ",
  "name": "RELIANCE",
  "ts": "2026-08-29T10:41:00+05:30",
  "harvest_id": "h...",
  "freshness_sec": 12,
  "spot": 2484.5,
  "dte": 3,
  "grade": "WATCH",
  "chain_bias": "BEARISH",
  "structure": {
    "oi_pcr": 0.68,
    "vol_pcr": 0.51,
    "regime": "CALL_WRITING_CEILING",
    "call_wall": 2520,
    "put_wall": 2460,
    "gamma_wall": 2480,
    "max_pain": 2480,
    "iv_skew": 1.1,
    "skew_edge": false,
    "straddle_chg_pct": -7.4,
    "atm_ce_state": "Short Buildup",
    "atm_pe_state": "Long Buildup"
  },
  "futures": {
    "ok": true,
    "basis": -2.5,
    "state": "SHORT_BUILDUP",
    "oi_change_pct": 4.2
  },
  "htf": { "daily": "BEARISH", "h4": "BEARISH", "gate": "ALLOW_SHORT" },
  "anomalies": [
    {
      "type": "OTM_SIZE",
      "side": "PE",
      "strike": 2460,
      "oi_added": 82000,
      "vol_x": 3.1,
      "label": "Put Writing"
    },
    { "type": "STRADDLE_CRUSH", "value": -7.4 }
  ],
  "trade": null,
  "why_not": "Futures short buildup + ceiling agree, but no location (spot mid-range). Watch put wall 2460."
}
```

The board is a list of `ChainReport` sorted by: TRADEABLE first, then WATCH with more anomalies, never by a fake 0–100.

---

## 11. Data plane to keep (do not rebuild)

Harvest is the one part of this repo that is pointed the right way. Keep and simplify.

```text
Fyers REST + WS
        │
        ▼
 Market Gateway (limiter, 429, single-flight, harvest-only REST)
        │
        ▼
 Symbol Book (Redis + memory)
   chain, spot, futures, history 15/D, timestamps, last ChainReport
        │
        ▼
 Anomaly Engine (pure, no I/O)
        │
        ▼
 Board (last_scan) → Radar UI
```

Keep:

| Module | Why |
| :--- | :--- |
| `fyers_market.py` | REST + local greeks + store-first |
| `fyers_auth.py` | daily token |
| `fyers_websocket.py` + `spot_stream.py` | LTP |
| `rate_limiter.py` | 180/min operational |
| `symbol_store.py` | the book |
| `market_gateway.py` | thin door — finish it, don’t invent a second |
| `radar_scheduler.py` | 180s harvest, TOP-34 first |
| `history_sweeper.py` | 15m/D off the chain critical path |
| `scan_jobs.py` | job the UI can poll |
| `fno_stocks.py` | universe |
| `option_analytics.py` **calculators only** | PCR, walls, max pain, buildup, straddle, skew |
| `levels.py` futures + walls helpers | after they read the store only |

Change:

- Harvest must **store futures** in the same pass (batched quotes of `{SYM}{YY}{MON}FUT`, one 50-batch — not 40 serial after the walk).
- Harvest must **persist previous chain digest** (walls, PCR, per-strike OI/vol) for migration and real volume spikes.
- After each name: run `analyze_chain`, upsert `ChainReport` into the book, publish incremental board.
- `attach_heavy` / LIS / idea-book-on-starved-data: gone.

---

## 12. UI rebuild (one component)

Replace `OptionFlowRadar.tsx` (3216 lines) with a desk of three regions:

1. **Session chrome** — auth, harvest progress, store age, index + VIX from the book.
2. **Board** — TRADEABLE / WATCH lists. Columns: name, bias, regime, futures state, top anomaly, age. Click selects.
3. **Chain pane** — structure strip, anomaly list, full near-ATM grid (CE/PE OI, ΔOI, vol, IV), trade card or `why_not`.

Rules:

- No process / flow / tape tabs.
- No Scan that starts a second universe walk; Scan = “run harvest if idle”.
- Incremental paint while harvest runs (Phase 1 listing fix stays).
- Home becomes this page. `Dashboard.tsx` loses the button farm.
- Mobile: board stacked above detail. Same data.

Auth modal and SystemStatus stay.

---

## 13. Teardown map (files)

This is a product deletion, not a refactor of every strategy “to store-only.”

### 13.1 Delete from the product (UI + routes + boot)

| Path | Action |
| :--- | :--- |
| `frontend/components/StockAnalysis.tsx` | delete |
| `frontend/components/QuantDashboard.tsx` | delete |
| `frontend/components/VATScanner.tsx` | delete |
| `frontend/components/MA7200Scanner.tsx` | delete |
| `frontend/components/RSIScanner.tsx` | delete |
| `frontend/components/RSIDivergenceScanner.tsx` | delete |
| `frontend/components/HighVolumeScanner.tsx` | delete |
| `frontend/components/ConfluencePanel.tsx` | delete |
| `frontend/components/LiveTradeSignal.tsx` | delete |
| `frontend/components/GreeksHeatmap.tsx` | delete |
| `frontend/components/NiftySentimentCards.tsx` | delete |
| `frontend/components/ActiveStrategy.tsx` | delete |
| `frontend/components/MarketStateDetector.tsx` | delete |
| `frontend/components/OptionChainTable.tsx` | fold into Radar chain pane or delete |
| `frontend/components/MCPTradingPanel.tsx` | hide in v1 (code can stay) |
| `backend/app/routes/strategies.py` | delete |
| `backend/app/routes/ma7200.py` | delete |
| `backend/app/routes/rsi.py` | delete |
| `backend/app/routes/ma_crossover.py` | delete |
| `backend/app/routes/confluence.py` | delete |
| Stocks/HV/live-signal/greeks/sentiment/news routes in `market_data.py` | strip |
| `/options/analysis`, `/options/adjustments` | replace with Radar symbol report |

### 13.2 Delete or quarantine as libraries (no import from Radar)

| Path | Action |
| :--- | :--- |
| `services/strategies/vat.py` | quarantine |
| `services/strategies/ma7200_*.py` | quarantine |
| `services/strategies/rsi_*.py` | quarantine |
| `services/strategies/ma_crossover.py` | already dead; delete |
| `services/confluence.py` | delete |
| `services/nifty_sentiment.py` | fold index PCR/VIX into Radar context or delete |
| `services/high_volume_scanner.py` | delete rec; volume rank can be a book query later |
| `radar_signal_engine.py` | replace; keep `classify_signal` + `derive_oi_change_pct` |
| `fno_intelligence.py` | delete as orchestrator |
| `desk_decision.py` | logic absorbed into Layers 1–4; do not call as a score |
| `rsi_desk.weight_radar_row` | delete |

### 13.3 Rewrite

| Path | Action |
| :--- | :--- |
| `option_flow_radar.py` | harvest + persist + `analyze_chain` only. ~1/3 the size |
| `routes/option_flow_radar.py` | board / symbol / job only |
| `OptionFlowRadar.tsx` | new desk UI |
| `Dashboard.tsx` | Radar is the app |
| `lib/api.ts` | strip dead clients |

### 13.4 Keep, maybe slim

`idea_engine.py` / `idea_book.py` / `execution.py` / `oi_clusters.py` / `mtf_engine.py` — **only** if they implement Layer 5 hysteresis and location **on top of ChainReport**. If they stay coupled to LIS/grades, rewrite a small `trade_lock.py` instead of dragging 2.5k lines of process-trade mythology.

`levels.py` is 1045 lines of pivots/Camarilla/CPR. v1 location = **VWAP + OI walls + ATR**. Classic pivots are optional later.

---

## 14. Implementation phases (after this report is accepted)

Do **not** start another 3-phase I/O program. The book works enough.

### Phase A — Freeze and strip (1 sitting)

- Radar is the only view.
- Comment out / remove other Dashboard buttons and their routes.
- Stop importing `weight_radar_row`.
- Leave harvest running so the book stays warm.
- No behaviour change to scoring yet — just stop the bleeding of extra scans.

### Phase B — Anomaly engine (pure, test-first)

- New `backend/app/services/chain_anomaly.py`.
- Unit tests from **real recorded chains** (LICHSGFIN case in the fix report is the first fixture: must return WAIT / CONFLICTED, not BUY).
- Fixtures: writing ceiling, put floor, futures short vs CE buying trap, cluster, wall shift, quiet chain, illiquid name.
- Harvest writes `ChainReport` next to the chain in the symbol store.

### Phase C — Board contract

- `/radar/last` (or `/radar/board`) returns reports, not flagged/watch/alert_box/ideas soup.
- Incremental upsert per symbol as today.
- Frontend paints three buckets.

### Phase D — Trade cards

- Location + hysteresis + invalidation.
- Still no orders.

### Phase E — Delete the zoo

- Remove quarantined files, dead routes, dead docs pointers.
- `readme.md` describes one product.

Do not mix Phase B with a UI redesign of the old 3216-line component. New UI reads the new contract.

---

## 15. Test bar (what “works” means)

A rebuild is done only if:

1. **Quiet chain stays quiet.** High PCR-balanced name, no size, no futures event → QUIET, no card.
2. **Writing ceiling does not become BUY CE.** LICHSGFIN-style: PCR 0.66, HTF bear, gamma wall bear, call long buildup on ATM → CONFLICTED or BEARISH WATCH, never BUY CE.
3. **Futures short + PE writing → short bias.** Not “put writing is bullish” in isolation.
4. **One-print wonder does not TRADEABLE.** Same bias must persist one more harvest.
5. **Illiquid name never TRADEABLE.** Floors hold.
6. **No page except Radar** can start a Fyers chain walk (assert in tests / gateway counters).
7. TOP-34 board in ≤ 15s, full 187 attempted ≤ 75s (keep existing harvest targets).
8. Row click with warm store: **0 Fyers REST**.
9. Empty anomalies list is illegal. If grade ≠ QUIET, `anomalies.length >= 1`.
10. `why_not` is always populated when `trade` is null and grade is WATCH.

---

## 16. Risks and non-goals

### Risks

- **Fyers OI is EOD-ish / jumpy.** `oichp` is often 0; we already reconstruct. Anomaly engine must prefer **absolute OI delta + persistence**, not a 8.0 vs 8.1 percent flip.
- **No true 3-day option volume without extra REST.** v1 uses prior harvest snapshot of the same contract (free). Do not spend 187 extra history calls on option symbols.
- **Futures symbol mapping** (`NSE:RELIANCE25SEPFUT` etc.) can miss. Missing futures = WATCH, not silent skip-as-spot.
- **Redis off** still wipes memory on restart. Keep Redis on in the local contract (`config.py` already defaults `redis_enabled=True`).
- **Temptation to keep scores** so the UI looks busy. Reject it. Empty is correct.

### Non-goals for this rebuild

- Auto orders
- Backtests
- News / Grok
- VAT / RSI / 7/200 revival
- MCP trading UI
- Tick-level OI (Fyers will not give it)
- Multi-user auth
- Predicting price

---

## 17. Evidence index (this tree)

| Claim | Where |
| :--- | :--- |
| One-best-strike | `option_flow_radar.py` `_process_option_chain` sort + `best = scored[0]` |
| Harvest starves VWAP/EMA | `_scan_one` `attach_heavy=False`; `_underlying_from_store` sets `vwap=ltp`, `vwap_dev_pct=0`, `above_ema20=chg>=0` |
| Dummy delivery | `radar_signal_engine.py` `build_scored_contract` `delivery_ratio=1.0` |
| 3-day vol skipped | `_scan_one` `fetch_vol_history=False` |
| Anomalies API empty | `routes/option_chain.py` `"anomalies": []` |
| Intelligence “institution” = round strike | `fno_intelligence.py` `_analyze_institutional_flow` |
| Opening hour NO-TRADE | `fno_intelligence.py` `_classify_market_state` |
| WAIT forced under Bullish column | `market_data.py` `_apply_setup_side` |
| RSI re-ranks Radar | `rsi_desk.py` `weight_radar_row`; called from `scan_all` `_weight_hit` |
| Deep analytics unused by Radar | `deep_analyze_chain` imported by `fno_intelligence` / levels, not `radar_signal_engine` |
| Hardcoded empty product surface | Dashboard 10 buttons; Radar 3216 lines; StockAnalysis 1487 |
| Market gateway is a 96-line wrapper | `market_gateway.py` |
| Process lock skipped on listing | harvest `attach_heavy=False`; idea engine ENTER_COMPOSITE=70 |
| Fake EMA construction | `_get_underlying_data(light=True)`: `ema20 = ltp * (0.998 if green else 1.002)` |
| `classify_signal` ignores underlying | `underlying_price_change_pct` in signature, never used |
| ACCUMULATION leak | OI>5% (below the 8% “hard” filter) still labelled “Smart Money Accum.” and passes Layer 1 |
| Vol spike includes self | `chain_relative_vol_spike` peers include the contract → ratio pulled toward 1.0 |
| Structural fallback bypasses vol filter | `_structural_candidate` + `vol_spike_ratio=1.0` still scores |
| Flagged = A/A+ only | `_repartition_hits`; A+ needs unusual+LIS≥60+greeks; harvest rarely produces A |
| Idea promote starved | 3/4 snapshots over ≥180s; scheduler interval is 180s; first pass cannot lock |
| MTF `allowed_side=NONE` | missing 4H → `plan_execution` NO_PLAN → cluster magnets idle |
| Two buildup thresholds | radar 8% vs `option_analytics` DOI 5% |
| Gamma not price-normalised | 0.001–0.05 “healthy” for both NIFTY and a ₹500 stock |
| Vega unused | accepted in `compute_greek_quality_score`, never scored |
| Custom harvest hatch | `POST /radar/scan` → `scan_all` bypassing `ensure_pass` |
| `keepRadar` hidden polls | after first Radar visit, 2s `/radar/last` runs on every other view |
| Gateway not exclusive | harvest still calls `fyers_market.get_option_chain`, not `market_gateway` |
| 5m not in the book | `/radar/candles` and backtest request resolution `5` → `store_miss` |

---

## 18. Recommended next action

Do not write more architecture READMEs.

When this report is accepted:

1. Phase A strip the UI to Radar-only (stop extra scans today).
2. Phase B implement `chain_anomaly.py` with the LICHSGFIN-style WAIT fixture **before** any new pixels.
3. Point harvest at that engine.
4. Replace the Radar board contract.
5. Delete the zoo.

Until then, treat LIS grades, Quant, VAT, RSI, 7/200, Stocks Option, Confluence, and Live Trade Signal as **non-authoritative**. They will recommend trades. They are not to be followed.
