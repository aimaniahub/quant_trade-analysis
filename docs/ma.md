# ma.md — 7/200 Cross × Option Chain as a real trade desk

**Status:** RESEARCH + PLAN ONLY. Do not implement from this file until reviewed.  
**Date:** 2026-08-14  
**Related (do not replace blindly):** `docs/7_200_cross.md` (freshness / first-cross rules), `docs/routingfix.md` (harvest already writes `derived.ma7200` + stored OC), `docs/MTF_Momentum_README.md`  
**Code today (read-only context):** `ma7200_scanner.py`, `routes/ma7200.py`, `MA7200Scanner.tsx`

---

## 0. One sentence

A 15m 7/200 EMA cross is only a **location + timing flag**. It becomes a trade only when the **option chain + futures OI** show new money on the same side, price is not already extended, and we can name **instrument, invalidation, target, and time-stop**.

That is how desks actually use a crossover. The current page stops at “candidate list + 2/5 generic OC checkboxes + ATM CE/PE suggestion”. That is why it feels worthless.

---

## 1. What you asked for

You already have a 7/200 scanner. Alone it is not a product. You want it **useful** by combining:

1. Stocks that **just crossed** 7 over/under 200 (or are **about to**),  
2. with a **real option-chain read**,  
3. into something that looks like a **quant / institutional setup**, not a blog-style “golden cross = buy calls”.

This file is the research, the diagnosis of what we built, and the plan. **No application code is changed by this document.**

---

## 2. What exists today (honest audit)

### 2.1 Two steps that never become one setup

```
Scan F&O 15m  →  first-cross-in-N-days list  →  user clicks Analyze Chain  →  2/5 rules  →  CONFIRMED / AVOID
```

- **Step 1** is a momentum filter (geometry + volume + first-cross + age). That part is directionally right.  
- **Step 2** reuses `fno_intelligence.get_analysis_summary` and scores five **generic** OC rules.  
- Confirmation is **≥ 2 of 5**. Max pain and a soft PCR can “confirm” a bullish cross with **no actual CE buying or PE writing**.  
- Suggested strikes are always **ATM CE / next CE / bull call spread** (mirror for PE). No IV, no liquidity, no wall, no stop, no R:R.  
- UI still says “Direct Fyers 15m API” even after harvest. Analyze is **one symbol, on click**, so the board never shows “this name is sponsored / this name is a fake break”.  
- Empty board is common: `crosses_in_15d == 1` is very strict. User then thinks the feature is dead.

### 2.2 What the current 5 rules actually check

| Side | Rule | Problem |
| :--- | :--- | :--- |
| Bull | Call Long Buildup ATM/+OTM | Correct *if* CE LTP↑ + OI↑. On stocks this is thin and often missing. |
| Bull | Put writing ATM/below | Correct institutional support. Mixed with “short covering” in the same bucket. |
| Bull | OI PCR > 1.0 | Index heuristic. Stock PCR is noisy; 1.0 is not a law. |
| Bull | Max pain > spot | Weak on single-stock options. Max pain is an expiry-gravity story, not a 15m trigger. |
| Bull | ATM CE volume dominant | Volume ≠ direction (could be writers). |

Bear side is the mirror. Opposite primary buildup → CONFLICT only if hits < 3. So a messy chain can still print CONFIRMED.

### 2.3 What `7_200_cross.md` already locked (keep)

These are **good candidate rules**. Do not throw them away:

- 15m EMA 7 / EMA 200 only.  
- Close on the correct side of **both** EMAs.  
- Volume ≥ 1.5× prior 10 bars.  
- First valid cross in ~15 calendar days (anti-chop).  
- Soft cap on extension from the 200 (~2.5%).  
- Skip open/close 15m edges.

Gaps in that doc: it **explicitly left OC philosophy unchanged**. That is the hole this file fills.

### 2.4 What harvest already gives us (do not re-fetch)

From `routingfix.md` / current store:

- `history.15` (40d) → 7/200, VWAP, rel-vol, ADX/ATR can be CPU.  
- `history.D` → daily bias / 200-day context.  
- Full OC ±14 (indices ±20) → confirm without a second Fyers walk.  
- `derived.ma7200` already written on harvest.  
- Spot, optional futures on flagged names.

**Plan constraint:** 7/200 page must be a **CPU desk on the Redis book**. Analyze Chain must not start a private Fyers loop.

---

## 3. Research — what serious people actually say

Sources read for this note (not an endorsement of any vendor product):

| Source | What it is | Takeaway we keep |
| :--- | :--- | :--- |
| [Investopedia — MAs / Golden Cross](https://www.investopedia.com/articles/active-trading/052014/how-use-moving-average-buy-stocks.asp) | Classic TA | Cross is **lagging**. Looks reliable *after* the move. Regular false signals. Do not treat as prediction. |
| [Investopedia — ADX](https://www.investopedia.com/articles/trading/07/adx-trend-indicator.asp) | Trend strength | ADX < 20 = range. Do not take MA crosses. ADX > 25 = trend-follow allowed. |
| [QuantInsti — MA strategies](https://blog.quantinsti.com/moving-average-trading-strategies/) | Quant blog | Triple MA / extra confirmation exists because **dual cross alone is noisy**. Sideways = overlapping lines = fake signals. |
| [LuxAlgo — why crosses fail](https://www.luxalgo.com/library/concept/moving-average-crossovers/) | TA explainer | In a range, averages flatten and **braid**. Filters (separation, slope, trend strength) exist to kill that. |
| [FXNX — 200 as gatekeeper](https://fxnx.com/en/blog/best-moving-average-crossover-settings-stop-hunting) | Practitioner | Only take *bullish* fast/slow crosses **if price is already respecting the 200 as regime**. 200 is a filter, not just a line to poke. |
| [r/Daytrading — profitable EMA users](https://www.reddit.com/r/Daytrading/comments/1uw9ox2/people_who_are_profitable_using_ema_crossovers/) | Live traders | Consensus: EMA cross as **confirmation of a trend already starting**, not the only trigger. Fail in chop; you only know it was chop *after*. |
| [r/algotrading — MA crossover](https://www.reddit.com/r/algotrading/comments/1ov3g5r/moving_average_crossover_strategy/) | Backtesters | 50/200 and 9/21 **work in trends, fail in ranges**. ADX + volume improve consistency. Pure cross is not enough. |
| [r/algotrading — ADX filter](https://www.reddit.com/r/algotrading/comments/1rpvp24/avoiding_lateralisation/) | Backtesters | Simplest fix: **skip if ADX < 20–25**. EMAs will still cross; there is no trend behind them. |
| [r/algotrading — 9/21 paper + RVOL](https://www.reddit.com/r/algotrading/comments/1u2g8ye/59_days_of_paper_trading_a_921_ema_crossover/) | Journal | Relative volume filter (e.g. yesterday > 80% of 10-day avg) cuts low-conviction signals. |
| [Zerodha Varsity — OI](https://zerodha.com/varsity/chapter/open-interest/) | India F&O textbook | Price + OI 4-box is the institutional primitive. OI alone has **no direction**. Abnormally high OI + fast price = leverage / panic risk. |
| [Groww — advanced option chain](https://groww.in/blog/advanced-option-chain) | India retail desk | Same 4-box. High CE OI = resistance, high PE OI = support. PCR is **sentiment**, not a buy button. Extreme PCR is more *reversal* than *trend follow*. |
| [NiftyTrader — PCR traps](https://www.niftytrader.in/markets/how-to-read-an-option-chain-2/) | India OC | PCR must be read **with price**. Confirming vs diverging. Post-2024 F&O is different; do not treat PCR as automatic bull/bear. |
| [Choice India — indicators for options](https://choiceindia.com/blog/best-indicators-for-option-trading) | India | Practical stack: **EMA/VWAP = trend, OI/PCR = sentiment, VIX = buy vs sell premium**. |
| [Kotak Neo — OI for intraday](https://www.kotakneo.com/investing-guide/intraday-trading/how-to-use-open-interest-for-intraday-trading/) | Broker edu | Breakout + **rising OI** = sponsored. Breakout without OI = fade risk. Pair OI with **ADX + MA + VWAP**. High OI strikes = liquidity + magnets. |
| [Sensibull / Indian OC practice](https://sensibull.com/) | How India actually screens | Long/short buildup, PCR, IVP, futures OI — the language our confirm step must speak. |

### 3.1 Consensus that is not optional

1. **A crossover is a lagging regime/timing flag.** By the time 7 crosses 200 on 15m, part of the move has printed. That is acceptable **only if** we enter the *continuation*, not the whole impulse.  
2. **Most MA-cross PnL is destroyed in sideways braid.** First-cross-in-15d is one anti-chop rule. ADX, slope, and “price spent most of 15d on one side of 200” are the others.  
3. **Volume (or RVOL) is the cheapest quality filter.** No volume = no one is there.  
4. **Option chain does not predict direction by itself.** It answers: *is new money agreeing, or is this a vacuum / writer trap?*  
5. **Price + OI (and CE/PE split) is the confirmation language.** PCR and max pain are secondary. On **stocks**, futures OI 4-box is often cleaner than stock-option PCR.  
6. **Walls are targets and invalidations, not decorations.** Highest PE OI below = support to lean on / trail against. Highest CE OI above = first target / fade zone.  
7. **IV decides the vehicle.** High IV → defined-risk debit spread or skip buying. Low/normal IV → ATM–slight OTM option. VIX / IVP is the switch.  
8. **Institutions do not “buy the cross”.** They ask: trend? sponsorship? location? liquidity? then they size a defined invalidation.

### 3.2 What Reddit / algo people specifically warn

- “I only know it was chop after the 4th cross.” → we already count crosses in 15d; keep that, but also show **NEAR** names instead of an empty board.  
- “Use EMA as secondary confirmation.” → flip our product: **OC/futures can be the thesis; 7/200 is the trigger window.** Or: 7/200 is the trigger; OC is the *permission*. Never either alone.  
- “9/21 without RVOL was junk.” → keep 1.5× on the cross bar; add day RVOL from harvested 15m.  
- Paper traders who added **volume + ADX** reported fewer but cleaner trades. That is the right bias for a desk: **fewer cards, real setups.**

---

## 4. How powerful is “just crossed” vs “2 bars ago” vs “about to cross”

This is the part you asked to pin down.

Think of 7 vs 200 on 15m as a **regime flip of the short impulse vs the session mean**.

| State | bars_ago / geometry | Power | How to use |
| :--- | :--- | :--- | :--- |
| **NEAR** | 7 approaching 200 (gap < ~0.15–0.25% of price), not crossed, volume rising, ADX climbing | **Watch only.** Highest *optionality*, zero permission to buy premium. | Desk row: WATCH. Pre-build the OC read. Enter **only after close-through**. |
| **FRESH 0** | Last **closed** 15m bar *is* the cross (REST history has no forming bar; this is “just printed”) | **Highest EV if not extended** and OC agrees. | Primary candidate. Enter on next 15m open or small pullback to 7/200 cluster. |
| **FRESH 1** | One closed bar after the cross | Still early. Continuation if price held the 200 and did not blow 2% away from it. | Primary if `extension_from_200` low and OI still building. |
| **FRESH 2** | Two closed bars after the cross | Allowed **only if** price is still near the 200 (not a chase) and OI/volume still expanding. | Secondary. Prefer pullback-to-7 entry. If already +1.5–2.5% from 200 → skip. |
| **STALE ≥ 3** | Older | Late. The cross is now a **regime label**, not a trigger. | Do not list as a new trade. May still feed confluence as “15m bias”. |
| **RE-CROSS** | 2+ valid crosses in 15d | Chop / mean-reversion. | Hide from the trade board. Optional “noise” tab for debugging only. |

**Product rule (recommended):**

```
TRADE board   = FRESH 0–2  AND  first-cross-in-window  AND  extension < X%  AND  OC/futures permission
WATCH board   = NEAR (approaching)  OR  FRESH without OC yet
IGNORE        = stale, re-cross, session-edge, weak volume, ADX dead, OC conflict
```

Why 2 bars is still useful: a 15m bar is 15 minutes. Two bars = 30 minutes. That is still “this morning’s event”, not yesterday’s golden cross. After 3–4 bars the move is either working (you are chasing) or failing (you are catching a knife).

**Near-to-cross is the missing product.** You said you want it. Research agrees it is a **pre-alert**, never an entry. The close through 200 + volume is the actual trigger. Showing NEAR fills the empty-board problem and lets the desk pre-read the chain.

---

## 5. The institutional stack (how a desk would actually trade this)

Four questions, in order. Fail any hard gate → no trade.

```
1. REGIME     Is this a trend environment? (ADX, daily/60m bias, Nifty not in NO-TRADE)
2. TRIGGER    Did 7 just take 200 (or is it one close away) with volume?
3. SPONSOR    Are futures + options adding on that side? (price+OI 4-box, CE/PE split)
4. LOCATION   Are we still near the 200 / VWAP, not into the opposite wall?
5. VEHICLE    What contract, what stop, what target, what time-stop?
```

### 5.1 Regime (CPU on harvested 15m + D)

| Check | Pass |
| :--- | :--- |
| 15m ADX(14) | ≥ 20 to allow; ≥ 25 preferred |
| Daily / derived MTF | Not strongly opposite the cross (from store `derived.mtf` / D bars) |
| Nifty / index state | If Nifty is NO-TRADE / violent mean-revert, **haircut stock setups** or require extra OC hits |
| Session | Prefer 09:30–15:00 IST. Skip first and last 15m for *entries* (alerts can still fire) |

### 5.2 Trigger (existing 7/200, tightened)

Keep current geometry. Add:

- **Slope:** EMA200 not flat. Bull: 200 rising or at least not falling hard. Bear: inverse. A 7 flick across a dead-flat 200 is braid.  
- **Base:** in the 15d before the cross, ≥ ~65–70% of closes on the *old* side of 200 (true break, not a mid-range wiggle). This is already hinted in `7_200_cross.md` §7 P1.  
- **RVOL day:** today’s 15m volume vs prior sessions (harvest already has 40d).  
- **NEAR metric:** `|EMA7 − EMA200| / price` and shrinking for 2–3 bars, plus volume rising.

### 5.3 Sponsor — this is the option-chain job, rewritten

Do **not** keep “2 of 5 including max pain”.

Use a **permission score** built from primitives India desks already speak.

#### A. Futures 4-box (Zerodha / Groww) — required when we have `snapshot.futures`

| Price | Fut OI | Name | Permission |
| :--- | :--- | :--- | :--- |
| ↑ | ↑ | Long buildup | **Agrees with bull cross** |
| ↓ | ↑ | Short buildup | **Agrees with bear cross** |
| ↑ | ↓ | Short covering | Weak / squeeze — do not treat as A-grade |
| ↓ | ↓ | Long unwinding | Weak — do not treat as A-grade |

No futures print → do not invent one. Score OC only, and require a higher OC bar.

#### B. Option CE/PE 4-box at ATM ± 1–2 strikes (not whole-chain PCR first)

For each nearby strike, classify **that contract**:

| Premium (LTP) | OI | Meaning |
| :--- | :--- | :--- |
| ↑ | ↑ | Long buildup (buyers opening) |
| ↓ | ↑ | Short buildup (writers opening) |
| ↑ | ↓ | Short covering |
| ↓ | ↓ | Long unwinding |

**Bull permission (need a clear story, not 2 random ticks):**

- **Primary (need 1):** ATM/ITM-1 **PE short buildup** (put writing = support) **OR** ATM/OTM-1 **CE long buildup** (call buying = fuel).  
- **Plus one of:** put wall below spot holding; futures long buildup; rising PE OI below ATM; CE volume not just one print.  
- **Hard fail:** ATM PE long buildup + CE short buildup (someone is betting the cross fails).  
- **Hard fail:** price already into the **call wall** (first resistance) with CE writing accelerating — late.

**Bear permission (mirror):**

- Primary: ATM/OTM **CE short buildup** (call writing) **OR** ATM **PE long buildup**.  
- Hard fail: CE long buildup + PE writing collapsing.  
- Hard fail: already smashed through the put wall.

#### C. PCR — demote

- Use **change in PCR** and **ATM-band PCR**, not a magic 1.0 / 0.85.  
- Rising PCR while price rises = puts being added (often writing) = bull support.  
- Falling PCR while price rises = calls being added. Must split **CE long vs CE short** via LTP.  
- Extreme PCR is a **reversal** warning (Groww), not a reason to add to the 7/200 trend.

#### D. Max pain — demote or drop for stocks

Useful on **index expiry day** as a magnet. Almost useless as a 15m stock-cross confirm. If kept, it is a *soft* location hint only, never a hit that can carry the setup alone.

#### E. Walls and liquidity

- Put wall (max PE OI below) = **invalidation zone** for longs (break + hold under = thesis dead).  
- Call wall (max CE OI above) = **first target** for longs / **do not chase** if spot is already there.  
- Skip names where ATM option volume/OI is below a floor (illiquid stock options = cannot express the idea cleanly). Prefer futures if we ever add them; until then mark **NO VEHICLE**.

#### F. IV / VIX — vehicle switch

| IV / IVP | If permission is GO | Vehicle |
| :--- | :--- | :--- |
| Low–mid | Buy ATM or 0.40–0.55Δ option | Outright CE/PE |
| Elevated | Same direction, **debit spread** to the wall | Defined risk |
| Crash / event IV | Often **skip buying** | Or wait; writers own that tape |

India VIX only for index-linked haircut. Stock IV from the chain.

### 5.4 Location

- Spot still **on the correct side of 200 and 7**.  
- Prefer spot **≥ VWAP** for longs (session institutional mean). Opposite for shorts. Choice India / Kotak both pair VWAP with OI.  
- Extension from 200: hard skip if already beyond ~2.0–2.5% on 15m (we already have this).  
- Distance to opposite wall: if target < 0.6× risk to invalidation → no trade.

### 5.5 Vehicle (what CONFIRMED must print)

A confirmed card is **not** a badge. It is a ticket:

```
SIDE        LONG / SHORT
TRIGGER     7/200 FRESH 1 · first in 15d · vol 1.8×
SPONSOR     Fut long buildup · PE writing 810 · CE LB 820
VEHICLE     820 CE  (or 820/840 bull call if IV high)
ENTRY       15m close hold above 200, or pullback to 7
STOP        Below 200 cluster  OR  below put wall (whichever closer + buffer)
TARGET1     Call wall / next CE OI
TARGET2     1.5–2.0 × risk (optional)
TIME STOP   No follow-through by +4 closed 15m bars → flatten
INVALID     Opposite CE/PE 4-box flips, or spot closes back through 200
```

Without those fields, the page stays a scanner.

---

## 6. Scoring model (plan — formulas can be tuned later)

Do **not** change `detect_7_200_cross` scoring until this is approved. New scores sit **on top**.

### 6.1 Trigger score `T` (0–100) — already close

Reuse `momentum_score` idea:

- bars 0: +40 · bars 1: +28 · bars 2: +16  
- first-cross-in-window: +25  
- volume vs 1.5×: up to +20  
- rising volume into cross: +8  
- 200 slope aligned: +7  
- extension > 2%: −15  
- ADX < 20: **hard 0** (not a score cut — a gate)

NEAR names get a separate `approach_score` (gap shrinking + volume + ADX), never mixed into TRADE.

### 6.2 Permission score `P` (0–100)

| Component | Weight | Notes |
| :--- | ---: | :--- |
| Futures 4-box agree | 25 | 0 if missing; 8 if covering/unwinding only |
| Primary CE/PE story | 30 | writing or buying as in §5.3 B |
| Secondary flow | 15 | wall + volume |
| No hard-fail conflict | 15 | 0 if conflict (and veto) |
| Liquidity ATM | 15 | OI/volume floor |

**Gates:**

- `P < 40` → AVOID  
- conflict hard-fail → AVOID regardless of T  
- `T ≥ 55` and `P ≥ 60` → **SETUP**  
- `T ≥ 70` and `P ≥ 75` and futures agree → **A-SETUP**

Old “2/5 rules” goes away.

### 6.3 Composite desk rank

```
desk_score = 0.45 * T + 0.55 * P
```

Permission is slightly heavier than the cross. That matches the research: the cross is common; **sponsorship is rare**.

---

## 7. Why the current page feels worthless (map to the plan)

| User feeling | Cause | Fix in this plan |
| :--- | :--- | :--- |
| Empty list | Strict first-cross + no NEAR | WATCH board for approaching + harvested derived |
| “Confirmed” but no trade | 2/5 + ATM CE stub | Ticket: vehicle, stop, target, time-stop |
| Click Analyze on each row | Confirm is a side quest | Auto-score every FRESH name from **stored** chain |
| PCR/max pain nonsense | Index heuristics on stocks | Demote; futures + strike 4-box first |
| Late / chase | bars_ago 2 with huge extension still listed | Extension hard skip; 2-bar only if still near 200 |
| Not “quant” | No gates, no R:R, no regime | ADX + VWAP + walls + IV vehicle |
| Slow / quota | Old “direct Fyers” UX | CPU on harvest book (already built) |

---

## 8. Product — what the page should become

Three columns, one desk. Not “scan then maybe analyze”.

### 8.1 Board A — TRADE (permissioned)

Only FRESH 0–2 + first-cross + `P` passed.  
Columns: name, side, age, vol×, ADX, fut state, primary flow, desk_score, vehicle, stop, t1.  
Row expand = full ticket + mini chain (ATM ±2) from store.

### 8.2 Board B — WATCH (near + unconfirmed fresh)

NEAR crosses and FRESH names waiting on P.  
Purpose: “do not miss the close” without selling the cross early.

### 8.3 Board C — REJECT / noise (collapsed)

Re-cross, stale, conflict, illiquid. One-line reason. Builds trust that the filter is working.

### 8.4 Header

```
15m book 186/189 · 3 TRADE · 7 WATCH · harvest 48s
```

No “Direct Fyers history API” copy. Manual **Rescore book** = CPU over store.

### 8.5 What we will not add in v1 of this redesign

- Tick-by-tick live EMA engine (`7_200_cross.md` Phase 3–4). Harvest 15m close is enough until the desk is useful.  
- Auto order placement.  
- Turning 7/200 into a second radar / second Fyers harvest.  
- Reviving legacy multi-TF MA (`/ma-crossover`).

---

## 9. Implementation plan (when you say build)

Phased. Do not skip. Do not rewrite `idea_engine` / radar scoring.

### Phase A — Make confirm real (backend, store only)

1. New module or functions in `ma7200_scanner.py` (keep `detect_7_200_cross` as-is):  
   - `score_near_cross(candles)`  
   - `permission_from_snapshot(snap, cross_type)` using store chain + futures + spot  
   - `build_ticket(...)`  
2. Scan job: for every symbol with `history.15`, compute trigger **and** permission. No Fyers.  
3. Replace `confirm_with_option_chain` 2/5 + max-pain carries with `P` + gates. Keep a `legacy_rules` block in the payload for a release or two so we can compare.  
4. Analyze endpoint becomes “explain this snapshot” (same CPU), not “fetch OC”.

### Phase B — Desk UI

1. TRADE / WATCH / REJECT tabs.  
2. Auto-filled permission on every FRESH row (no mandatory click).  
3. Ticket panel instead of CONFIRMED badge.  
4. Harvest-age banner. Settings stay (fast/slow/window/vol) but defaults stay 7/200/15d/1.5×.

### Phase C — Regime polish

1. ADX + 200 slope + VWAP from stored 15m.  
2. Index haircut from stored Nifty state.  
3. IV → outright vs debit spread.  
4. Time-stop / invalidation text on the ticket.

### Phase D — only if A–C are used daily

1. Bar-close incremental update (no full REST).  
2. Push NEAR → FRESH when the 15m closes.  
3. Optional hook into idea book / confluence as a **source**, not a second writer.

---

## 10. Data we need (already vs new CPU)

| Field | Source after harvest | Used for |
| :--- | :--- | :--- |
| 15m OHLCV ≥ 205 bars | `history.15` | 7/200, near, ADX, VWAP, RVOL, extension |
| Daily bars | `history.D` | HTF veto |
| Spot | `spot` | walls, ATM |
| Chain ±14 | `chain.rows` | 4-box, PCR, walls, IV, liquidity |
| Futures quote | `futures` if present | 4-box agree |
| Nifty state | stored Nifty snap | haircut |
| Derived ma7200 | already written | fast pre-filter |

**Do not harvest extra for this page.** If futures missing, OC-only permission with a higher bar.

---

## 11. Risks

| Risk | Handling |
| :--- | :--- |
| Empty TRADE board | Expected. WATCH + harvest banner. Empty A-setups is success, not failure. |
| Stock OC too thin | NO VEHICLE; do not fake ATM CE. |
| Intraday OI on NSE is imperfect | Varsity itself warns live OI can be messy. Prefer **change + LTP** together; never OI alone. |
| 15d first-cross too strict | Keep as default; settings already allow window. Do not loosen in code to “make the table busy”. |
| User wants every cross | That is the old worthless product. Refuse in the plan. |
| Confirm too slow / too loose | Permission heavier than trigger; hard fails exist. |

---

## 12. Open decisions (answer before coding)

| # | Question | Suggested default |
| :--- | :--- | :--- |
| 1 | Allow bars_ago **0,1,2** or only **0–1** on TRADE? | TRADE 0–1; bars 2 only if extension < 1.2% and P ≥ 70 |
| 2 | NEAR as first-class WATCH? | **Yes** |
| 3 | Auto-permission every FRESH row from store? | **Yes** (this is the whole point) |
| 4 | Keep max pain as a scoring hit? | **No** on stocks; optional expiry-day note on indices |
| 5 | Futures required for A-SETUP? | **Yes** if quote exists; else cap at SETUP |
| 6 | ADX hard gate? | **Yes**, 20 |
| 7 | Default vehicle | ATM–0.45Δ outright if IV mid; debit spread if IV high |
| 8 | Push into idea book? | Not in A–C |

---

## 13. Acceptance criteria (done when)

1. Opening 7/200 does **not** start a Fyers history storm; it scores the harvest book.  
2. Every FRESH name shows **permission** without a click.  
3. CONFIRMED without stop/target/vehicle **cannot appear**.  
4. A braid / 3rd cross in 15d cannot appear on TRADE.  
5. A bullish cross into a call wall with CE writing prints **AVOID**, not CONFIRMED via PCR.  
6. NEAR names exist so the desk is alive **before** the close.  
7. You can explain one ticket out loud in 20 seconds like a desk: *trigger, sponsor, vehicle, die-level*.

---

## 14. One-line product summary

> **Show me F&O names whose 15m 7 just took the 200 (or is one close away), only if the move is the first in two weeks, still near the line, and the chain/futures are adding on that side — then give me the option, the stop, and the wall. Everything else is noise.**

---

## 15. Suggested build order when approved

```
Phase A   permission + ticket from store (no UI redesign yet; Analyze becomes real)
Phase B   TRADE / WATCH / REJECT desk UI
Phase C   ADX / VWAP / IV vehicle / index haircut
Phase D   bar-close NEAR→FRESH (optional)
```

No application code was changed for this document. Next step: answer §12, then implement Phase A.

---

*End of research + plan.*
