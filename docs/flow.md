# FLOW.md — Stop the 10-Second Flip. Find the One Process Trade.

**Date:** 14 August 2026  
**Status:** Research + design dump (not implemented)  
**Problem this file exists to solve:**  
The radar / live analysis *changes every few seconds*. Direction, strike, LIS, and “best trade” shuffle. The trader cannot tell which idea is **prominent** and which is **noise**.  

This is not mainly a classification bug. Classification (CE/PE matrix) was already fixed.  
This is a **stability + confirmation** problem.

---

## 0. One-line product rule

> **Scan every 10–30 seconds. Do not *decide* every 10–30 seconds.**  
> A process trade is born only when flow, structure (pivots / OI walls), and time all agree — and it stays locked until it is *invalidated*, not until the next snapshot is prettier.

---

## 1. The real problem (what the user is feeling)

### What it looks like on screen

- 10:15:12 — RELIANCE 1480 CE, Fresh Call Buying, LIS 74, BUY  
- 10:15:22 — RELIANCE 1460 PE, Put Writing, LIS 71, BUY  
- 10:15:32 — RELIANCE 1500 CE, Call Writing, LIS 68, SELL  
- 10:15:42 — back to 1480 CE, LIS 69  

Same stock. Four “best trades” in 30 seconds. None of them is a process. All of them are **snapshots**.

### Why this destroys trust

A human desk does not flip a trade idea every 10 seconds.  
A human desk says:

1. “Bias for the day is long above 1478 (pivot + put wall).”  
2. “Flow is confirming: PE writing + CE buying near ATM.”  
3. “The process trade is: buy 1480 CE on a VWAP reclaim, stop under S1 / PDH.”  
4. That idea lives for 20–90 minutes unless **invalidated**.

Our engine currently behaves like a restless intern re-ranking the tape.

---

## 2. Why our engine flickers (root causes in *this* repo)

These are the actual mechanisms, not vibes.

### 2.1 Snapshot scoring, no memory

`radar_signal_engine.py` scores **the current chain snapshot**.  
There is no:

- last-N-snapshot history per symbol  
- “same direction for 3 consecutive scans”  
- locked Active Idea  
- hysteresis (enter at 70, leave at 45)

So every poll is a brand-new election. The winner changes.

### 2.2 Thresholds sit on a knife-edge

Hard filters:

- OI change ≥ 8%  
- premium change ≥ 1.5%  
- vol spike ≥ 1.5×  
- ATM distance ≤ 7%

A strike at 7.9% OI is “NEUTRAL”. Next tick 8.1% and it is “Fresh Call Buying”.  
Premium 1.4% → 1.6% flips the whole CE/PE matrix cell.  
LIS is a continuous 0–100, so **rank order shuffles even when nothing meaningful happened**.

### 2.3 ATM itself walks

Spot crosses a strike → ATM changes → “best near-ATM strike” changes → the featured contract jumps 20–50 points. The idea looks new. It is the same stock, same bias.

### 2.4 Day-open % change is jumpy

`option_price_change_pct` and `oi_change_pct` are usually vs previous close / day start.  
Early session (9:15–10:00) these percentages are violent. Mid-session they still bounce on bid/ask flicker from Fyers chain snapshots.  
**OI on NSE is not a 10-second institutional heartbeat.** Treating it as one is the bug.

### 2.5 “One best strike” is the wrong product unit

The radar returns the highest-scoring contract. Humans trade **a symbol + a direction + a zone**.  
Strike is an instrument, not the thesis.

### 2.6 Fast refresh of a slow signal

- Radar UI auto-scan ~90s (was even faster before).  
- Live trade signal poll 30s.  
- Confluence 60s.  
- Scheduler 10 min, but any manual / job scan rewrites the featured list.

A 10-second *feeling* also comes from: websocket LTP + re-derived labels, or the user hammering refresh / watching LiveTradeSignal + Radar + Confluence at once. Three panels, three clocks, three rankings.

### 2.7 Confluence is a photo, not a process

`confluence.py` already says “2+ sources agree → ACTIONABLE”. Good.  
But it still reads the **latest radar row**. If radar flipped, confluence flips. No hold time. No pivot layer. No “do not demote until invalidation”.

### 2.8 What we already have (do not rebuild)

We already compute, in pieces:

- Full CE/PE matrix + LIS v2 + Greek quality + A+/A/B/C grades (`radar_signal_engine.py`)  
- Max pain, PCR regimes, call/put walls (`option_analytics.py`)  
- HTF gate + PCR ceiling/floor (`desk_decision.py`)  
- MA crossover + radar + intel + news weights (`confluence.py`)  
- VWAP / EMA20 as a soft layer

**Missing is the glue that makes one trade stay on the board:** persistence, pivots, futures OI, idea-lock, invalidation.

---

## 3. What the research actually says

Pulled from flow desks, UOA research, Indian F&O practice, and signal-hygiene engineering. Not astrology.

### 3.1 Unusual flow is *not* “large”. It is “out of character”.

Geeks of Finance (2026): unusual = violation of **that name’s baseline**, not a round number.

Five signals that matter when **two or more fire together**:

1. **Volume >> prior OI** at that strike (new bet, not rotation)  
2. **Premium spend large vs that stock’s normal options notional** (rupees, not just contracts)  
3. **Aggressive lifts** (buyer paying up / sweeping) — urgency  
4. **Strike that is a real bet** (not a hug-the-money hedge)  
5. **Expiry that matches urgency** (weeklies = “soon”; LEAPS = horizon)

Four false positives that look huge and are not directional (~30–40% of scanner flags, Cboe / TradeAlgo):

1. Earnings-week IV / straddle (both sides, vol bet)  
2. Dealer hedge prints (mechanical, no view)  
3. Rolls (close near expiry + open further — two “unusual” legs, net unchanged)  
4. Multi-leg spreads (matching size at two strikes = capped bet)

**Implication for us:** a single high-LIS strike on one snapshot is not a trade.  
It is a *candidate* until we rule out hedge / roll / spread / expiry noise.

### 3.2 Flow alone is a coin flip with a slight tilt

TradeAlgo / Cboe-cited ranges (treat as order-of-magnitude, not gospel):

- Vol/OI > 3: ~58% chance of a meaningful 10-day directional move  
- Sweeps: ~62% same-day directional vs ~48% for blocks  
- Premium + Vol/OI filters: mid-50s hit rate  
- Hedging / rolls / spreads: 30–40% of flags  
- Combining flow **with technical structure**: cited ~12% higher win rate (MTA)  
- Three-factor confirmation (flow + chart + catalyst): ~40% fewer false trades  

**Nobody serious trades raw UOA.** They use it as *fuel*, then demand a map (levels) and a clock (persistence).

Sensamarket’s best line:  
> *The alerts don’t count. It’s observing the same trades over days instead of minutes.*

For our intraday product: **same thesis over 10–30 minutes, not 10 seconds.**

### 3.3 Indian F&O already has the “map”

NSE desks do not start from LIS. They start from:

| Object | How it is read | Stability |
|---|---|---|
| Highest PE OI strike | **Support / put wall** (writers defending) | Hours |
| Highest CE OI strike | **Resistance / call wall** | Hours |
| Change-in-OI today | Who is *adding* defence today | 15–60 min |
| PCR (OI) | Regime, not a trigger. Low PCR ≈ call writing ceiling. High PCR ≈ put writing floor. Must be read **with price** (Zerodha Varsity). | Hours |
| Max Pain | Expiry magnet. Stronger last 1–2 days. Weak as a day-0 directional. Karthik: freeze it, add a buffer, do not chase daily wiggle. | Days, wiggles daily |
| Futures OI + price | Long buildup / short buildup / covering / unwinding — **real money** | 15–60 min |
| VWAP | Intraday fair value. Institutions defend / fade it. | Session |
| Classic / Camarilla pivots | Pre-computed from **yesterday** H/L/C. Do not move. Shared map. | All day |
| PDH / PDL / PDC | Previous day high / low / close | All day |

Zerodha Varsity (Karthik Rangappa), critical comment:  
> You cannot tell buy vs sell from OI alone. You must look at **OI and price together**.

That is exactly our CE/PE matrix. It is necessary. It is not sufficient.

### 3.4 Pivots are the missing “where”

Why pivots (and why they stop flicker):

- Calculated **once** from previous session High, Low, Close.  
- They do not change when Fyers OI ticks.  
- The whole market sees the same levels (self-fulfilling liquidity).  
- Highest-probability day trades in the literature are **pivot + VWAP confluence**, not pivot alone, not flow alone.

**Classic floor pivots**

```
P  = (H + L + C) / 3
R1 = 2P − L
S1 = 2P − H
R2 = P + (H − L)
S2 = P − (H − L)
R3 = H + 2(P − L)
S3 = L − 2(H − P)
```

Bias: **above P = long-preferred day, below P = short-preferred day.**  
That bias should not flip until price *accepts* the other side (close of a 15m bar, not a 10s wick).

**Camarilla (very common on Nifty / BankNifty / liquid F&O)**

```
R3 = C + (H − L) × 1.1/4
S3 = C − (H − L) × 1.1/4
R4 = C + (H − L) × 1.1/2
S4 = C − (H − L) × 1.1/2
```

Indian desk usage:

- Open **inside S3–R3** → range day. Fade R3 / buy S3.  
- Break **R4 / S4** → trend day. Do not fade. Trade with the break.  
- Stockgro / TrendSpider / TradingView all describe the same split: fade inside, trend outside.

**This is gold for us:** Camarilla tells us whether today’s *process* is mean-reversion or breakout *before* any option print. Flow then confirms which side has the fuel.

### 3.5 Signal hygiene: hysteresis, not re-election

LuxAlgo “Signal Hygiene” and industrial hysteresis say the same thing:

> Price (or a score) hovering at a threshold will cross, recross, and cross again. Each flicker is a new signal unless you add hysteresis.

Rules used in every serious alerting system:

- **Enter** when score ≥ 70 **and** persisted N bars.  
- **Exit / flip** only when score ≤ 45 **or** hard invalidation.  
- Alerts **once per bar close** (15m), not on every tick.  
- Confirmed mode = zero-repaint for live trading.

A 10-second radar is allowed as a **tape**.  
A 10-second radar is forbidden as a **decision**.

---

## 4. What a “sure process trade” actually is

“Sure” does not mean 90% win rate. Anyone selling that is lying.  
A **process trade** means:

1. We know **why** we are in (thesis in one sentence).  
2. We know **where** we are wrong (invalidation level).  
3. We know **where** we take money (target at next wall / pivot).  
4. The idea does not change because a snapshot wiggled.  
5. Multiple *independent* clocks agree.

Independence matters. LIS + vol spike + OI % are **one family** (same chain snapshot).  
That is one vote, counted three times. That is why it feels loud and still dies.

### The three clocks

| Clock | Horizon | Examples | Allowed to flip the idea? |
|---|---|---|---|
| **Slow structure** | Session / multi-day | Daily trend, classic pivot P, OI walls, PCR regime, max pain, 7/20 or 20/50 MA | Sets the *allowed side* |
| **Process / fuel** | 15–60 min | Futures buildup, persistent option flow, VWAP side, Camarilla regime | Confirms the *process* |
| **Trigger** | 1–5 min | 5m/15m reclaim of VWAP or pivot, sweep of PDH, candle close | Times the *entry only* |

**Trigger never changes direction.**  
If slow structure says long-only, a 10-second put print does not make us short. It is noise or a hedge.

---

## 5. The Process Trade Stack (proposed)

A trade becomes **PROMINENT** only if it clears this stack.  
Anything that fails stays on a quiet tape / watch list. It does not hijack the headline.

### Layer A — Day map (compute once at 9:14, refresh only on new daily bar)

For every symbol:

- Classic P, S1–S3, R1–R3  
- Camarilla S3/S4, R3/R4  
- PDH, PDL, PDC  
- Opening range (first 15 min high/low) after 9:30  
- Yesterday’s max PE OI strike (put wall) and max CE OI strike (call wall)  
- Distance of spot to each, in % and in ATR  

**Regime tags (stable all morning unless 15m acceptance):**

- `ABOVE_P` / `BELOW_P` / `AT_P`  
- `INSIDE_CAM` (between S3–R3) vs `TREND_UP` (above R4) vs `TREND_DN` (below S4)  
- `AT_PUT_WALL` / `AT_CALL_WALL` / `BETWEEN_WALLS`  
- `VWAP_ABOVE` / `VWAP_BELOW` (this one *does* update, but only on 5m close)

This layer does not use live OI % at all. It cannot flicker.

### Layer B — Fuel (option + futures), but **persisted**

Keep the CE/PE matrix. Change *when* we trust it.

For each symbol, store a rolling window of snapshots (e.g. every 60–90s, last 20):

```
t0  direction=BULL  strike_family=1480CE  lis=74  label=Fresh Call Buying
t1  direction=BULL  strike_family=1480CE  lis=71
t2  direction=BULL  strike_family=1460PE  lis=69  label=Put Writing
t3  direction=MIXED
t4  direction=BULL  strike_family=1480CE  lis=76
```

**Persistence score (0–1)**

- Same *direction* for last K of N snapshots (recommend K=3 of last 4, ≈ 4–6 minutes if scan is 90s; if we ever scan at 10s, K=12 of 15)  
- Same *strike family* (±1 strike) gets a bonus  
- Direction flips inside the window → persistence = 0, idea cannot be PROMINENT  

Also add, from data we already almost have:

- Futures: price ↑ + OI ↑ = long buildup (bull fuel)  
- Futures: price ↓ + OI ↑ = short buildup (bear fuel)  
- PCR regime from `option_analytics` (ceiling / floor)  
- Call wall / put wall **change-in-OI today** (defence being added, not just leftover)  
- Cluster: 2+ neighbouring strikes same side  

**Premium rupees, not just %.**  
`premium_spent ≈ volume × LTP × lot_size`  
A 40% move in a ₹2 option is retail noise. A 8% move in a ₹80 ATM with 5L volume is fuel.

### Layer C — Location (the pivot confluence the user asked for)

Flow is allowed to become a trade **only near a level**.

Bullish process is “sure” only if **at least one** is true:

- Spot within 0.3–0.5 ATR of: S1 / S2 / Camarilla S3 / put wall / VWAP / PDH reclaim / ORH break  
- And VWAP side agrees (or is being reclaimed on a 5m close)  
- And we are not kissing the call wall from below with expanding CE writing  

Bearish process, mirror: R1 / R2 / Cam R3 / call wall / VWAP fail / PDL break.

**Confluence count (this is the “prominent” score):**

```
+2  price at classic pivot (P/S1/R1) ± 0.25 ATR
+2  price at OI wall (PE wall for long, CE wall for short)
+2  VWAP agree or 5m reclaim/reject
+2  Camarilla regime agrees (fade inside, trend outside)
+1  PDH/PDL/OR break in direction
+1  daily / 4H bias agrees (desk_decision HTF gate)
+1  7/20 or 20/50 MA side agrees (already in MA scanner)
```

Cap 11.  
**PROMINENT process trade requires location_score ≥ 4 and persisted fuel.**

This is the whole point of adding pivots: they are a **second, independent, non-flickering vote**.

### Layer D — Quality / risk (already specified in v3)

Keep as filter, not generator:

- Delta 0.30–0.60 preferred  
- Reject delta < 0.20  
- ATM distance ≤ 7% (tighter 5% for “sure”)  
- Greek quality ≥ 8/20  
- IV not hostile for a debit  
- Expiry: for directional *process* prefer 7–30 DTE. 0–2 DTE is a separate scalp playbook (we already have the gamma scalp PDF). Do not mix them.

### Layer E — Hard vetoes (stand aside)

No PROMINENT trade if any:

- Slow structure vs fuel conflict (daily bear + “fresh call buying” = WATCH only)  
- Both CE and PE unusual in similar size → spread / straddle / earnings IV  
- Expiry day + inside Camarilla + max pain nearby → pin risk, do not hunt directional  
- First 15 minutes (opening auction chaos) — map only, no lock  
- Last 15 minutes — manage, do not open new process  
- India VIX shock / news headline opposing (news_context already exists)  
- Persistence window mixed  
- LIS high but location_score = 0 (flow in the middle of nowhere)

---

## 6. The locked Active Idea (this kills the 10-second flip)

### Product objects (three, not one)

| Object | Refresh | What the UI shows |
|---|---|---|
| **Tape** | 10–30s | Raw unusual prints. Small, quiet, scrollable. Never the headline. |
| **Candidates** | 60–90s | Passed hard filters, not yet persisted. “Watch”. |
| **Active Idea** | Event-driven | The one prominent process trade per symbol (and a top-5 market board). Locked. |

### Lock rules

**Promote Candidate → Active Idea** when all are true:

1. Direction persisted K-of-N  
2. Location_score ≥ 4  
3. Fuel classified as Fresh Buying or Writing (not Exhaustion / Neutral)  
4. Grade A or A+ after layers  
5. No hard veto  
6. HTF gate does not oppose (`desk_decision` already has this philosophy)

**Hold the idea** even if LIS drops from 78 → 64, or the “best strike” hops 1480 → 1500.  
Update the *instrument* quietly. Do not change the *thesis*.

**Invalidate (only then flip or kill)** if any:

- 15m close beyond invalidation level (below S1 / put wall / VWAP for a long)  
- Persistence window flips and stays flipped for 2 extra snapshots  
- Opposing unusual **writing** appears at the wall we were using as support  
- Futures OI flips from buildup to opposite buildup  
- Score decays below exit threshold (hysteresis: enter 70 composite, exit 45)  
- Time stop: thesis not working in 5–10 trading days for swing; for intraday, 45–90 minutes or 2×ATR dead money  

Hysteresis diagram:

```
composite
   80 |          ******** Active Idea (locked)
   70 |         *        ********
      |        *                 *
   45 |-------*-------------------*----  exit / unlock
   30 |  *                         ****  dead / watch
```

Same number (60) can mean “still in” or “not yet in” depending on history.  
**That is the entire cure for flicker.**

### One prominent trade per symbol

Never show two opposite ideas for RELIANCE at once.  
If both sides print, status = `CONFLICT / NO_TRADE`.  
The board of the day is sorted by:

```
prominence = persistence * location_score * (lis/100) * unusual_score_factor
```

Top 3–5 only are “sure process” candidates. Everything else is tape.

---

## 7. How to score “accuracy” (so we stop guessing)

We cannot claim accuracy without a ledger. Add a silent logger now, even before UI.

For every Active Idea:

```
symbol, side, strike_family, opened_at, location_tags[],
lis, persistence, location_score, grade,
invalidation, target,
spot_at_open, spot_after_15m, 30m, 60m, EOD,
option_pnl_if_held, hit_target, hit_stop, still_open
```

Metrics that actually answer “is this more real”:

- **Follow-through rate:** % of ideas where spot moved ≥ 0.4 ATR in idea direction within 30–60 min  
- **Flip rate:** how often headline direction changes per symbol per hour (this number must collapse)  
- **False promotion rate:** promoted then invalidated < 10 min  
- **Dead money rate:** neither 0.4 ATR nor stop in 60 min  
- **Conflict-avoidance:** how often we correctly stayed out when both sides printed  

Target after this design (honest, not marketing):

| Metric | Today (felt) | Target |
|---|---|---|
| Headline flips / symbol / hour | many (every scan) | ≤ 1 |
| Ideas promoted per day (top FNO) | dozens of fakes | 8–20 real |
| 30-min follow-through | poor | ≥ 55% |
| Stand-aside when conflicted | rare | default |

55% with a 1.5–2R target is a process. 80% “sure” is not a design goal.

---

## 8. Concrete process-trade recipes (what “sure” looks like)

These are the only setups that should be allowed to say **TRADE**.

### Recipe 1 — Put-wall bounce (long)

- Spot within 0.3 ATR of max PE OI strike **and** that strike is near S1 or Cam S3 or VWAP  
- PE OI ↑ + PE premium ↓ (Put Writing) **persisted**  
- Futures long buildup or at least not short buildup  
- Daily not opposed  
- Entry: 5m close back above the level  
- Stop: below the wall / S2  
- Target: pivot P, then call wall / R1  
- Instrument: ATM or 1 OTM CE, delta 0.35–0.55  

### Recipe 2 — Call-wall reject (short)

Mirror of Recipe 1. CE writing + price fail at R1/Cam R3/VWAP.

### Recipe 3 — Pivot break + flow fuel (trend)

- Camarilla **outside** R4 / S4 or 15m close through PDH/PDL  
- Fresh CE buying (long) or Fresh PE buying (short) persisted  
- VWAP on the same side  
- Do **not** fade. This is the opposite of Recipe 1.  
- Stop: back inside the broken level  
- Target: next Cam level / 1 ATR  

### Recipe 4 — VWAP reclaim after fuel already printed

- Unusual flow printed 10–40 minutes ago and **did not unwind**  
- Price dipped into VWAP / P / put wall and 5m reclaim  
- This is the “late but real” trade. Better than chasing the first 10s spike.

### Recipe 5 — Cluster / unusual box, still not auto-trade

- OI +25–30% and vol 3× at one strike, or multi-strike cluster  
- Goes to Alert Box (already in v3 spec)  
- Becomes a process trade **only after** Recipe 1–4 location attaches  
- Unusual without location = “someone did something”. Not our trade yet.

### Forbidden as headline trades

- Exhaustion / short covering / long unwinding as primary  
- Far OTM lottery (delta < 0.20) even with insane % OI  
- Opposite-to-HTF “sniper”  
- First 15 minutes of the cash session  
- Dual-side unusual (spread)  
- Score-only promotions (“LIS 81 so it must be right”)

---

## 9. Mapping onto what we should build (idea → modules)

No code in this file. Just the seams.

| New piece | Lives near | Notes |
|---|---|---|
| Daily pivot / Camarilla / PDH-PDL calculator | new `services/levels.py` | One shot after previous day OHLC. Cache until next session. |
| Opening range | same | After 9:30 IST |
| Snapshot ring buffer per symbol | `option_flow_radar.py` | Last 20 scored snapshots. Persistence math. |
| Persistence + hysteresis state machine | `radar_signal_engine.py` or new `idea_engine.py` | Candidate / Active / Dead |
| Location confluence | uses `option_analytics` walls + `levels.py` + VWAP | Independent of LIS |
| Futures buildup | `fyers_market` futures quote + OI | Already philosophically in `fnoanalysis.md` |
| Active Idea API | `routes/option_flow_radar.py` or confluence | `GET /radar/ideas` separate from `/radar/scan` |
| UI: lock the headline | `OptionFlowRadar.tsx` + `LiveTradeSignal.tsx` + `ConfluencePanel.tsx` | One board. Tape collapsed. Show “locked 18m ago, invalidate under 1472”. |
| Silent outcome logger | new jsonl / table | Required before we tune weights again |

**Do not** keep adding weights to LIS. LIS is already a 6-factor soup. Another factor inside LIS will still flicker.  
**Do** add a *second stage* that is allowed to say NO.

Priority order if we implement later:

1. Snapshot memory + persistence + hysteresis (kills 80% of the pain)  
2. Pivot / Camarilla / PDH + OI-wall location score  
3. Active Idea lock in API + UI  
4. Futures OI agreement  
5. Outcome ledger  
6. Only then retune LIS / unusual thresholds  

---

## 10. UI contract (so the screen stops lying)

### Headline card (one per symbol, sticky)

```
RELIANCE    LONG PROCESS    locked 10:22    hold
Spot 1484.2   above P 1478 · put wall 1470 · VWAP 1481
Fuel   Put writing 1470 PE + Call buying 1480 CE   persisted 12m (5/5)
Entry  5m reclaim of 1478–1481
Stop   1468 (below wall)
Target 1502 call wall / R1
Invalidation  15m close < 1468  or  futures short buildup
Strike  1480 CE  Δ 0.47   (instrument may update, thesis will not)
```

If the next scan prefers 1500 CE, the card does **not** rewrite. A small line can say “instrument hint: 1500 CE now more liquid”.

### Tape (optional, muted)

Scrolling unusual prints. No color panic. No “BUY” banner.

### Board of the day

Top 5 Active Ideas, sorted by prominence, not by last-tick LIS.  
A flip on this board should feel rare and important.

---

## 11. Worked example (why pivots make it “sure”)

**HDFCBANK** previous day: H=1680, L=1652, C=1668  

```
P  = 1666.7
S1 = 1653.3
R1 = 1681.3
Cam S3 ≈ 1658, R3 ≈ 1678   (approx)
Put wall from chain = 1660 PE (highest PE OI)
Call wall = 1680 CE
```

09:20 tape: 1700 CE volume spike, LIS 77. Radar today would scream BUY 1700 CE.  
Location_score: 0 (lottery strike, above call wall, first 15m). **Rejected.**

09:48: spot 1661, sitting on put wall + near S1 + below VWAP 1665.  
Fuel last 4 scans: PE writing at 1660, CE quiet, futures OI up on a bounce.  
Location_score: put wall + S1 + later VWAP reclaim = 6.  
**Active Idea: LONG. Entry on 5m close > 1665. Stop 1651. Target 1678/1680.**

10:02: a random 1640 PE print scores LIS 73. Tape notes it. Idea does **not** flip to SHORT.  
10:19: 5m close 1667. Process entry.  
11:10: still locked. Strike hint moved 1660 CE → 1670 CE. Thesis unchanged.

That is the product. One prominent trade. Sure *process*. Not sure *outcome*.

---

## 12. Research sources (for later rereads)

- Geeks of Finance — “What Is Unusual Options Activity, and How Do You Spot It?” (5 signals, 4 false positives, baseline-relative unusual)  
- TradeAlgo — “How to Read Unusual Options Activity” (2026): Vol/OI, premium $, sweeps vs blocks, 30–40% false flags, flow + technicals  
- Market Rebellion / Najarian — one-factor UOA scanners are noise; process the idea, don’t follow the print  
- Sensamarket — watch the *same* trades over days, not minutes  
- Cboe / OCC volume context — unusual is statistical deviation, not a contract count  
- Zerodha Varsity, Karthik Rangappa — Max Pain + PCR; OI must be read with price; max pain needs a freeze + buffer  
- Groww / Quantsapp — max pain as expiry magnet, not an intraday trigger  
- Investopedia / TradingSim / Equiti — pivot + VWAP confluence; pivots static, VWAP dynamic  
- Stockgro / TrueData / TradingView Camarilla — Indian index usage: fade S3/R3, trend beyond S4/R4  
- LuxAlgo Signal Hygiene + industrial hysteresis — different enter/exit thresholds to stop flicker  
- TradingView alert design — once-per-bar-close for signal alerts  
- Our own docs: `Option_Flow_Radar_Complete_Specification_v3.txt`, `flow fix.md`, `fnoanalysis.md`, `Option_Chain_Analyzer_Fix_Report.md`, `desk_decision.py`

---

## 13. Decisions to lock (so the next implementation does not argue)

1. **Headline unit = symbol + direction + zone. Not strike.**  
2. **Tape can be 10s. Decisions are 15m-close + persistence.**  
3. **Pivots / OI walls / VWAP are mandatory location votes, not decoration.**  
4. **Hysteresis is mandatory.** Enter ≠ exit threshold.  
5. **Conflict = no trade.** Dual-side unusual is a veto.  
6. **HTF opposition = cap at WATCH.** Already the desk_decision religion. Keep it.  
7. **Do not add more spices to LIS.** Add a second stage.  
8. **Max pain is a late-week magnet, not a Monday directional.**  
9. **0–2 DTE is a different sport.** Do not mix with process trades.  
10. **Accuracy is a ledger, not a feeling.** Log outcomes before the next scoring rewrite.

---

## 14. Bottom line

The analysis changes every ten seconds because we **re-elect a winner on every snapshot** from a noisy chain, with thresholds that sit on the edge, and no map of where price is allowed to be traded.

Professional flow is slower than that.  
Pivots, Camarilla, PDH/PDL, VWAP, and OI walls are the map.  
Persisted CE/PE flow + futures buildup is the fuel.  
A 5m/15m close at the level is the trigger.  
A locked Active Idea with hysteresis is the product.

**Prominent** = high location confluence + persisted fuel + no veto.  
**Sure process** = we know entry, stop, target, and we will not change our mind because the next 10-second print was louder.

Build that, and the screen finally looks like a desk instead of a slot machine.
