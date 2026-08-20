# rsi.md — RSI multi-timeframe × option chain (F&O reversal desk)

**Status:** IMPLEMENTED (R1–R2) with §12 locked to the intraday-reward defaults below.  
**Date:** 2026-08-16  
**Related:** `docs/ma.md` (same desk pattern), `docs/routingfix.md` (one harvest writer), `docs/7_200_cross.md`  
**Reuse (when coding):** `symbol_store`, `ma7200_desk.permission_from_snapshot` / `mtf_gate`, stored `history.15` + OC  
**Code today:** none. No RSI page exists. `Dashboard.tsx` has no RSI view.

---

## 0. One sentence

RSI ≤ 30 / ≥ 70 is only a **location of exhaustion**. It becomes a trade when **higher-timeframe RSI agrees**, **price starts to reclaim** the 30/70 line, and the **option chain + futures** show new money on the bounce (or fade) side — same harvest book, same permission engine as 7/200. Never a second Fyers walk.

---

## 1. What you asked for

A dedicated RSI scanner over ~180 F&O names on **5m / 15m / 1H**, lists:

- **Oversold** RSI ≤ 30  
- **Overbought** RSI ≥ 70  

And on the **same page**, the name that matters for this product:

> RSI below 30 **and** the option chain is **bullish** → oversold that can reverse.  
> (Mirror: RSI above 70 **and** chain is **bearish** → overbought that can fade / continue down.)

That second sentence is the product. A raw 30/70 table without OC is the same “worthless list” problem 7/200 had before the desk.

This file is research + implementation logic. **No application code is changed by this document.**

---

## 2. Research — what RSI actually is (and is not)

Sources used for this note:

| Source | Takeaway we keep |
| :--- | :--- |
| [Investopedia — RSI](https://www.investopedia.com/articles/active-trading/042114/overbought-or-oversold-use-relative-strength-index-find-out.asp) | 70 / 30 are **defaults**, not laws. Divergence and **failure swings** (leave 30, retest, stay above 30, break the swing high) are the real reversal patterns. Combine with structure / other indicators. |
| [Kotak — RSI](https://www.kotakneo.com/stockshaala/introduction-to-technical-analysis/relative-strength-index/) | Same: oversold *suggests* rebound. **Bullish swing rejection** = dip below 30, back above 30, shallow retest, then break. That is an *event*, not a level. |
| [Groww — indicators for options](https://groww.in/blog/best-indicators-for-option-trading) | RSI for options: overbought → trim longs / look short; oversold → opposite. **OI with price** is the confirmation of whether the trend has fuel. PCR is sentiment, not a button. |
| [Zerodha Varsity — OI](https://zerodha.com/varsity/chapter/open-interest/) | Price + OI 4-box. PE LTP↑ + OI↑ = put buying (bearish). PE LTP↓ + OI↑ = put writing (support). Direction lives in **premium + ΔOI**, not RSI. |
| [r/Daytrading — 5000-trade “buy RSI&lt;30”](https://www.reddit.com/r/Daytrading/comments/1pdj9f1/i_tested_that_rsi_oversold_strategy_on_5000/) | **Failed.** Oversold often means **downside momentum is strong**, not “must bounce”. Extremes can persist. |
| [r/Daytrading — don’t rely on 30/70](https://www.reddit.com/r/Daytrading/comments/1d4nsde/dont_just_rely_on_rsis_oversold_or_overbought/) | In a strong trend, RSI&gt;70 is **strength**, not a short. RSI&lt;30 in a waterfall is more selling, not a long. |
| [r/technicalanalysis](https://www.reddit.com/r/technicalanalysis/comments/1rk6sro/rsi_indicator_explained_how_to_actually_use_it/) | RSI **confirms a thesis**. Buying solely because RSI is oversold is gambling. Need structure. |
| [OANDA — MTF RSI](https://www.oanda.com/us-en/skills-and-insights/education/trading-strategies/building-strategies/mastering-rsi-trading-strategies/) | Higher TF sets bias. On a smaller TF, take **only the RSI that agrees** (e.g. daily up → only buy 1H RSI reclaim of 30). |
| [Goat Funded — day-trade RSI](https://www.goatfundedtrader.com/blog/best-rsi-settings-for-day-trading) | 15m: period 14–21. 5m entry only if 15m is **not deeply opposed**. Multi-TF is a filter, not three independent buy buttons. |

### 2.1 Consensus that is not optional

1. **RSI is momentum of closes, not “too cheap / too expensive”.** Below 30 = recent closes lost more than they won. That can be a *climax* or a *trend*.  
2. **Buying the first print under 30 is the losing version.** Reddit backtests and practitioner blogs agree: wait for **reclaim** (RSI crosses back through 30) or a failure swing.  
3. **HTF must not fight you.** 5m RSI 28 while 1H RSI is 62 is noise. 15m + 1H both ≤ 30 is a real oversold *regime*.  
4. **In a 4H downtrend, oversold is usually a continuation short, not a long.** Same `allowed_side` hard gate as 7/200.  
5. **Option chain answers “is anyone *paying* for the bounce?”** PE writing / CE long buildup / futures long buildup = sponsorship. PE long buildup + CE writing = they are betting it keeps falling.  
6. **OI alone has no direction.** Always pair with premium (LTP) change — already how `option_analytics.classify_buildup` works.  
7. **PCR / max pain do not make an RSI bounce.** We already demoted max pain on 7/200. Same here.

### 2.2 Two products people confuse (we will not)

| Naive scanner | Desk we will build |
| :--- | :--- |
| Dump every name with RSI 28 on 5m | Only **permissioned** extremes |
| “Oversold = buy CE” | Oversold + **bullish OC** + HTF not veto + (prefer) RSI reclaim |
| “Overbought = buy PE” | Overbought + **bearish OC** + HTF not veto; or *don’t fade* if OC is still buying |
| Poll Fyers every 30s for 180×3 histories | CPU on Redis harvest book |

---

## 3. How RSI combines with OI / option chain (the actual edge)

RSI says **where** we are in the impulse. The chain says **who is still adding**.

### 3.1 Oversold + bullish chain = bounce candidate (your core ask)

```
Trigger:  RSI(15) ≤ 30  (and ideally RSI(60) ≤ 40 or also ≤ 30)
Event:    RSI(15) just crossed back above 30   OR   still ≤ 30 but OC already flipping
Sponsor:  same permission as 7/200 LONG
          - PE short buildup (put writing) ATM/below
          - and/or CE long buildup ATM/+OTM
          - futures long buildup if present
Hard fail: 4H allowed_side = SHORT
           PE long buildup + CE writing (they want lower)
           NO_VEHICLE (thin ATM)
```

Why this pairing works when RSI-alone fails:

- RSI&lt;30 without sponsorship is a **knife**. Sellers still own the tape.  
- RSI&lt;30 **with put writing** means writers are defending a floor while the oscillator is stretched. That is how Indian F&O desks talk about a bounce.  
- RSI reclaim of 30 **with** CE long buildup is the “failure swing + new money” version (Investopedia + Sensibull language).

### 3.2 Oversold + bearish chain = do not catch

```
RSI(15) ≤ 30
+ PE long buildup / CE writing / futures short buildup
→ REJECT or “continuation short” WATCH — not a long ticket
```

This is the 5000-trade failure mode. The page must show it as **knife / continue**, not hide it and not sell it as a bounce.

### 3.3 Overbought + bearish chain = fade / continuation short

Mirror of 3.1. RSI(15) ≥ 70 + CE writing / PE long buildup + 4H not LONG-only.

### 3.4 Overbought + bullish chain = do not fade

RSI&gt;70 in a sponsored uptrend is **strength**. List it as MOMENTUM, not a short. Groww/Reddit both warn about this.

### 3.5 The 2×2 that the page is built on

| RSI zone | OC / futures permission | Board |
| :--- | :--- | :--- |
| ≤ 30 | Bullish (PE write / CE LB / fut LB) | **TRADE long bounce** (if reclaim + 4H allows) |
| ≤ 30 | Bearish or conflict | **REJECT** bounce; optional WATCH continuation |
| ≥ 70 | Bearish (CE write / PE LB / fut SB) | **TRADE short fade** (if reclaim down + 4H allows) |
| ≥ 70 | Bullish or conflict | **REJECT** fade; optional WATCH momentum |
| 30–70 | anything | Not on this page (unless NEAR 30/70) |

RSI extreme **without** a matching chain never prints a ticket. Same philosophy as 7/200.

---

## 4. Timeframes — what is powerful vs noise

Your brief asked 5m + 15m + 1H. Research ranking:

| TF | Role | Power |
| :--- | :--- | :--- |
| **1H (60m)** | Regime of the session. Both 15m and 1H extreme = High. | Highest |
| **15m** | Primary trigger for this desk (same bar family as 7/200 / harvest). | Primary |
| **5m** | Early / noisy. Only an entry *timing* tag if 15m already agrees. | Lowest |

**Priority (your table, kept and tightened):**

| Priority | Condition | Meaning |
| :--- | :--- | :--- |
| **A** | 15m **and** 1H both ≤ 30 (or both ≥ 70), OC agrees, 4H allows | TRADE |
| **B** | 15m extreme + 1H not opposed (1H &lt; 45 for oversold, &gt; 55 for overbought), OC agrees | SETUP / TRADE if reclaim |
| **C** | Only 15m extreme, 1H neutral, OC agrees | WATCH |
| **D** | Only 5m extreme | WATCH “early” — never a ticket alone |
| **E** | Any extreme, OC conflicts or 4H veto | REJECT |

**Fresh vs stale RSI**

| Event | Use |
| :--- | :--- |
| RSI just crossed **down through 30** (or up through 70) this bar or last bar | Fresh extreme — WATCH until reclaim + OC |
| RSI **still** ≤ 30 for 3+ bars, no reclaim | Stretched — only TRADE if OC is *already* flipping hard |
| RSI **reclaims** 30 from below (or 70 from above) | **Primary entry event** (failure-swing lite) |
| RSI was 28 two hours ago, now 42 | Stale. Do not list as oversold |

This is the RSI analogue of 7/200 `bars_ago` 0–2.

---

## 5. Data: same harvest technique (do not open a new Fyers loop)

`routingfix.md` already decided:

| Field | In store today | RSI use |
| :--- | :--- | :--- |
| 15m × 40d | **Yes** `history.15` | RSI(14) 15m, VWAP, EMA20, RVOL, ADX |
| 60m / 1H | **Derived** from 15m (`symbol_store.aggregate_ohlcv(..., 60)`) | RSI(14) 1H |
| 5m | **Not harvested** (row-click / radar chart only) | See §5.1 |
| Daily | `history.D` | Optional daily RSI / 4H MTF |
| Spot, OC ±14, futures | **Yes** | Permission + ticket (reuse `ma7200_desk`) |

**Rule:** RSI page is a **reader**. `GET` computes from Redis. UI polls 30–60s. Harvest cadence (180s) is enough; RSI(15) and RSI(60) do not need a private 180×3 history storm.

### 5.1 What to do about 5m (open decision, recommended default)

Harvesting 5m × 180 names every pass would re-open the quota hole we just closed.

**Recommended v1:** do **not** harvest 5m for the universe.

- Show **15m + 1H** as first-class columns.  
- 5m column = blank / “—” unless we later store a short 5m window **only for names already on WATCH/TRADE** (small batch, writer-only).  
- If you insist on 5m on day one: one extra harvest field `history.5` days=5 (~375 bars) **round-robin**, not every pass. Still writer-owned.

Do not let the UI call `get_historical_data(..., "5")` for 180 symbols.

### 5.2 RSI formula (Wilder, period 14)

Standard Welles Wilder (same family as our ADX):

```
change = close[i] - close[i-1]
gain = max(change, 0);  loss = max(-change, 0)
avg_gain = Wilder smooth 14
avg_loss = Wilder smooth 14
RS = avg_gain / avg_loss
RSI = 100 - 100/(1+RS)
```

Need ≥ 20–30 bars. 15m×40d is plenty. 1H derived from 15m: 40d ≈ 160 hour bars — enough.

Write `derived.rsi` on harvest (optional CPU): `{15, 60, ema20_15, vwap, rel_vol}` so the page is a tight read.

---

## 6. Institutional stack (copy the 7/200 shape)

```
1. REGIME     4H allowed_side + 1H RSI not opposed
2. TRIGGER    15m RSI extreme and/or reclaim of 30/70
3. SPONSOR    OC + futures permission (existing desk functions)
4. LOCATION   VWAP, EMA20, not already through the opposite wall
5. VEHICLE    IV → outright vs debit spread (already built)
```

### 6.1 Hard gates (same spirit as your 7/200 decisions)

| Gate | Rule |
| :--- | :--- |
| **4H `allowed_side`** | Oversold bounce = LONG ticket **forbidden** if 4H is firmly bearish. Overbought fade = SHORT ticket **forbidden** if 4H is firmly bullish. |
| **OC conflict** | Knife: oversold + PE long buildup → no long. Squeeze: overbought + CE long buildup → no short. |
| **Liquidity** | Same ATM vol/OI floor as 7/200. Else NO VEHICLE. |
| **Max pain** | Not used (same as 7/200 stocks). |
| **ADX** | Optional soft: if ADX ≥ 30 and 4H with the trend, treat oversold-against-trend as extra-dangerous (harder bounce). |

### 6.2 Reuse, do not rewrite

```
from ma7200_desk import (
    permission_from_snapshot,  # CE/PE 4-box + futures, no max pain
    mtf_gate,                  # 4H allowed_side
    mtf_for_symbol,
    build_ticket,              # IV vehicle, walls, time-stop
    session_vwap,
    compute_adx,
)
```

RSI desk adds: `rsi_wilder(candles)`, `rsi_event(prev, now)` (enter / leave / reclaim 30 or 70), `htf_priority(rsi15, rsi60, rsi5)`.

### 6.3 Ticket (oversold bounce example)

```
SIDE        LONG
TRIGGER     RSI15 27.4 → reclaim 31.2 · RSI60 29.8 · fresh 1 bar
SPONSOR     PE writing 810 · fut long buildup
VEHICLE     820 CE  or  820/840 call spread if IV rich
ENTRY       15m close hold + RSI back above 30
STOP        Below swing low / put wall / below 20 EMA (whichever closer)
TARGET1     VWAP then call wall
TIME STOP   No RSI hold above 40 within +4 15m bars → flatten
INVALID     4H flips SHORT, or OC flips to PE long buildup
```

A CONFIRMED row without those fields is the old worthless scanner.

---

## 7. Scoring (plan)

### 7.1 Extreme score `E` (0–100)

```
+ 35 if RSI15 in zone (≤30 or ≥70)
+ 25 if RSI60 in same zone
+ 10 if RSI60 not opposed (oversold: RSI60 ≤ 45)
+ 15 if reclaim event this bar or last bar
+ 10 if only 5m extreme (cap: cannot exceed 45 alone)
+ 5  if |RSI15 - 50| is larger (deeper extreme), diminishing after 20/80
```

### 7.2 Permission `P`

Exactly `permission_from_snapshot` for the **intended side**:

- Oversold → score as **BULLISH** (we want a bounce)  
- Overbought → score as **BEARISH** (we want a fade)

### 7.3 Board

```
desk_score = 0.40 * E + 0.60 * P     # permission heavier — RSI is common, sponsorship is not

TRADE   if E≥55 and P≥60 and mtf_gate ok and reclaim (or P≥75 without reclaim)
WATCH   if extreme but waiting reclaim / 4H mixed / only 5m / P 40–60
REJECT  if 4H hard fail or OC conflict or P < 40
```

Reclaim preferred for TRADE. Deep extreme + **already-flipping** OC (P≥75) can TRADE without reclaim — that is the “writers stepped in while RSI still 28” case you described.

---

## 8. Page structure

Not two dumb columns of 30/70. Same desk chrome as 7/200.

### 8.1 Header

```
RSI Desk (F&O) · Book age 41s · 15m 186/189 · Redis
Toggles: Oversold bounce | Overbought fade | Both
TF filter: 15m+1H (default) | include 5m early | All extremes
```

Poll `GET /strategies/rsi/scan` every **45–60s**. Backend is Redis CPU. Do **not** start a scan job that hits Fyers.

### 8.2 Tabs

| Tab | Contents |
| :--- | :--- |
| **TRADE** | Permissioned bounce / fade tickets |
| **WATCH** | Extremes waiting reclaim, NEAR 30/70, 5m-only, mixed 4H |
| **REJECT** | 4H veto, OC knife, thin options |

### 8.3 Columns

Stock · LTP · RSI 15 · RSI 60 · RSI 5 (optional) · Event (RECLAIM / FRESH / STUCK) · 4H · P · Desk · Vehicle

Row click → ticket (no Fyers). Same right-hand ticket panel as 7/200.

### 8.4 Visual of the *useful* oversold row (not the raw dump)

```
COALINDIA   LTP 407
RSI15 27.8  RSI60 29.1  RECLAIM
4H LONG allowed   P 72   SETUP
PE writing 400 · fut LB
Ticket: 410 CE · stop 398 (put wall) · t1 418 (VWAP/call wall)
```

POWERGRID with RSI15 28 but PE long buildup and 4H SHORT → **REJECT**, reason `OC_KNIFE` / `MTF_ALLOWED_SIDE`. That is a successful empty TRADE board, not a bug.

---

## 9. Implementation plan (when you say build)

Same harvest contract as 7/200. Do not add a third writer.

### Phase R0 — this file

Agree §5.1 (no universe 5m) and §12.

### Phase R1 — CPU engine (backend)

New, small:

- `backend/app/services/strategies/rsi_desk.py`  
  - `rsi_wilder`  
  - `classify_rsi_event`  
  - `scan_book()` → trade / watch / reject from `store.list_symbols()` + `history.15` + derived 60 + `permission_from_snapshot`  
- `backend/app/routes/rsi.py`  
  - `GET /strategies/rsi/scan` — sync CPU, seconds, not a Fyers job  
  - `GET /strategies/rsi/symbol/{sym}` — explain one name  
- Optional: harvest writes `derived.rsi15` / `derived.rsi60` to make the GET cheaper (not required for v1).

**Do not** copy `scan_universe`’s old job-per-history pattern.

### Phase R2 — UI

- `frontend/components/RSIScanner.tsx`  
- `Dashboard.tsx` view `rsi` + nav button  
- `api.ts` `api.rsi.scan()` / `api.rsi.explain(symbol)`  
- Poll 45s. Harvest banner. TRADE / WATCH / REJECT. Ticket panel.

### Phase R3 — polish

- Fresh-cross highlight (RSI just tagged 30/70).  
- Alert strip: 15m+1H both extreme + P≥60.  
- Volume ≥ 1.5× and “near VWAP / 20 EMA” as **filters**, not extra Fyers.  
- Optional 5m only for TRADE/WATCH names if we add a tiny writer batch.

### Phase R4 — only if used daily

- Divergence (price LL, RSI HL) as a WATCH boost.  
- Full Investopedia failure-swing detector.  
- Push into idea book as a source (not a second harvest).

---

## 10. Files that will be touched (later)

**New**

- `backend/app/services/strategies/rsi_desk.py`  
- `backend/app/routes/rsi.py`  
- `frontend/components/RSIScanner.tsx`

**Wire**

- `backend/app/main.py` — include router  
- `frontend/components/Dashboard.tsx` — view + button  
- `frontend/lib/api.ts` — `rsi.scan`

**Reuse, do not fork**

- `symbol_store.py`, `ma7200_desk.py` (permission, MTF, ticket, VWAP, ADX)  
- `option_analytics.py` (buildup / walls)  
- `mtf_service.py` / `mtf_engine.py`

**Do not touch**

- Radar scoring, idea_engine, VAT logic, harvest writer beyond an optional `derived.rsi` write.

---

## 11. Risks

| Risk | Handling |
| :--- | :--- |
| Empty TRADE | Expected. WATCH will be full of 5m noise if we show 5m. Default hide 5m-only. |
| “Buy every RSI 28” users | Page copy + REJECT reasons. Reclaim preferred. |
| 5m harvest storm | Forbidden in v1. |
| Stale 15m book | Same harvest banner as 7/200. Scan only symbols with `history.15`. |
| Oversold in a crash | 4H gate + OC knife. |
| Double-count with 7/200 | Different trigger. Same permission. Fine if both fire — confluence, not a second fetch. |

---

## 12. Open decisions (answer before coding)

| # | Question | Suggested default |
| :--- | :--- | :--- |
| 1 | Universe 5m RSI in v1? | **LOCKED NO.** 5m is noise and a Fyers storm. 15m + derived 1H. |
| 2 | TRADE require RSI reclaim of 30/70? | **LOCKED prefer yes.** Stuck extreme TRADE only if P≥75. |
| 3 | 4H `allowed_side` hard gate? | **LOCKED YES.** |
| 4 | Overbought shorts only when OC bearish? | **LOCKED YES.** Sponsored OB → WATCH momentum. |
| 5 | RSI period | **LOCKED 14** Wilder |
| 6 | Poll | **LOCKED 45s GET**, no job |
| 7 | Auto idea-book ingest | **LOCKED no** in R1–R2 |
| 8 | Volume / VWAP as extra filter? | **LOCKED soft.** Rel vol < 0.8× → WATCH (not REJECT). |

---

## 13. Acceptance criteria

1. Opening RSI does **not** call Fyers history or OC for the universe.  
2. 1H RSI is **derived from stored 15m**, not a 180-name `history 60` loop.  
3. Oversold + bullish OC + 4H LONG (or mixed) can TRADE; oversold + bearish OC cannot.  
4. Oversold + 4H firmly SHORT cannot print a LONG ticket.  
5. Overbought + bullish OC is not sold as a short.  
6. Every TRADE row has vehicle, stop, target, time-stop.  
7. UI poll does not start a scan job.

---

## 14. One-line product summary

> **Show F&O names whose 15m (and ideally 1H) RSI is stretched, but only promote a bounce when the chain is already bullish — and a fade when the chain is already bearish — and 4H is not on the other side. RSI finds the stretch. The book decides if it reverses.**

---

## 15. Suggested build order when approved

```
R1   rsi_desk + GET /strategies/rsi/scan  (store CPU, reuse permission/MTF)
R2   RSIScanner page + Dashboard button + 45s poll
R3   reclaim/fresh tags, volume/VWAP filters, optional 5m on shortlist
```

No application code was changed for this document. Next step: answer §12 (especially 5m and reclaim), then implement R1.

---

*End of research + plan.*
