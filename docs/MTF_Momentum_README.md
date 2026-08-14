# Multi-Timeframe Momentum Trades — Plan Before Build

**Date:** 14 August 2026  
**Status:** Design only. Do not implement until you approve.  
**Problem this file answers:**  
“Which one is the *good* trade? It still changes. Once confirmed, it should stay with that direction. Watch 15m — but also 1H and 4H. Find stocks strong on **all** frames, then read the chain, then take the real momentum trade.”

This sits **on top of** what we already built:

| Already live | What it does | What it still cannot do |
|---|---|---|
| Process lock (`flow.md`) | Stops 10-second snapshot flicker | Does not know if 4H/1H agree |
| Pivots / CPR / walls / VWAP | Where price is allowed | Not *which stock has the wind* |
| 15m 7/20 and 7/200 | One-frame momentum | One frame is not “all frames” |
| Option flow radar | Fuel (who is buying/writing) | Fuel without HTF = coin flip |
| Desk HTF gate | Soft daily oppose veto | Not a ranked MTF strength board |

So the remaining gap is not another LIS spice.  
It is a **top-down strength rank**, then chain, then a lock that dies only when the *higher* frames break.

---

## 0. One-line product rule

> **4H decides the allowed side. 1H says the move is still alive. 15m times the entry. Option chain is the fuel check. Once those four agree, the trade is confirmed and must not flip because a 15m candle wiggled.**

If 4H is bearish, a beautiful 15m bullish print is **not** a long. It is a pullback or a trap.

---

## 1. The real remaining problem (why it still “changes”)

Process lock stopped the *10-second* flip.  
You still cannot answer: **which name is the one to ride.**

Why:

1. **We rank snapshots, not campaigns.**  
   RELIANCE locked long at 10:22. HDFC looks cleaner at 11:05. The board reshuffles “best” even if both locks are valid. You feel like the trade changed.

2. **15m is too talkative.**  
   A 15m EMA unstack is noise inside a 4H uptrend. If 15m is allowed to vote on *direction*, the idea will keep changing. That is the Elder / Tradeciety / desk rule we have been violating by treating 15m as a peer of 4H.

3. **No “strength across frames” score.**  
   We do not currently sort the universe by: Daily + 4H + 1H + 15m all pointing the same way *and* expanding. So a sideways name with a hot option print can look as good as a name trending on every frame.

4. **Chain is being asked to pick direction.**  
   Chain should confirm or veto a direction that *structure already chose*. When chain is the first voter, writing/buying flips with every OI tick.

5. **Confirmation is too cheap.**  
   “Persisted 3 minutes + near a pivot” is enough to lock. That is good for *stability*. It is not enough for *this is the momentum horse*.

The user plan is the correct fix:  
**technicals on all frames first → then chain → then one directional momentum trade that is allowed to continue.**

---

## 2. What the research actually says (decisions, not quotes)

Pulled from Elder Triple Screen, Tradeciety MTF, TradeAlgo / JTA alignment studies, Bookmap, and how Indian F&O desks already talk (HTF first, then chain). Treat the exact win-rate numbers as order-of-magnitude, not gospel.

### 2.1 Always top-down. Never bottom-up.

Tradeciety’s strongest warning: if you start on 15m, you will either skip the higher frame or *bend* it to fit the 15m signal. That is exactly how fake longs appear in a 4H downtrend.

**Locked:** analysis order is Daily → 4H → 1H → 15m → chain. Never the reverse.

### 2.2 Three screens, not five

Elder (Triple Screen, still the standard):

| Screen | Role | Our frames |
|---|---|---|
| Tide | Allowed direction only | **Daily + 4H** |
| Wave | Is the move still alive / pullback complete | **1H** |
| Ripple | Entry timing only | **15m** |

Factor-of-4–6 between frames (Elder): Daily → 4H → 1H → 15m is the correct stack.  
15m and 5m are too close. 4H and weekly is for swing, not this product.

TradeAlgo / JTA-cited ranges (order of magnitude):

- Two-or-more-frame alignment ≈ mid-60s hit rate vs ~50% single-frame  
- Full 3-frame alignment much stronger than mixed (+3 vs +1)  
- Counter-HTF trades lose more often than they win (~58% cited)  
- MTF cuts false signals ~30–40%  
- Adding a *fourth* frame (e.g. 5m) adds almost no edge and a lot of flip

**Locked:** we use **Daily, 4H, 1H, 15m**. We do **not** add 5m or weekly as voting frames for this product. Weekly can be a soft tag later.

### 2.3 Different tools on different frames (do not copy-paste RSI everywhere)

Elder: trend tool on the tide, oscillator / pullback tool on the wave, trigger on the ripple. Same indicator on every frame = correlated noise, not confluence.

**Locked stack for us (India F&O, matches what we already compute):**

| Frame | Job | Technicals we will use |
|---|---|---|
| **Daily** | Allowed side | Close vs 20/50 EMA, HH-HL / LH-LL structure, daily bias we already have |
| **4H** | Campaign direction | Close vs 20/50 EMA, last two 4H structure (HH/HL or LH/LL), 4H VWAP-of-session is *not* used here |
| **1H** | Momentum still alive | EMA 20 slope + price side, 1H higher-low / lower-high, volume vs 20-bar avg |
| **15m** | Trigger only | 7/20 stack (already in `tech_filters`), optional 7/200 first-cross (`7_200_cross.md`) as *candidate*, not as flip |
| **Chain** | Fuel / veto | Existing CE/PE matrix, walls, PCR, futures buildup, process recipes |

### 2.4 15m does not own direction

Institutional phrasing (same idea everywhere):

- 4H = bias  
- 1H = liquidity / control  
- 15m = confirmation of structure  
- Lower than 15m = fill, not thesis  

**Locked invalidation ladder (this is how a confirmed trade “continues”):**

| Event | What we do |
|---|---|
| 15m 7/20 unstacks against us | **Hold.** Manage, do not flip. |
| 15m closes through VWAP against us | Tighten / trail. Still do not flip side. |
| 1H closes against the 1H 20 EMA **and** breaks the last 1H swing | **Downgrade to WATCH.** Stop adding. |
| 4H closes against the 4H 20 **or** breaks last 4H swing | **Kill the idea.** Side is no longer allowed. |
| Chain flips to opposite *buildup* (futures short buildup vs a long) **and** 1H is already weak | Kill. |
| Dual-side unusual on chain while 4H still with us | Stand aside on *new* size. Do not reverse. |

This is the rule that answers “once confirmed, continue that direction.”  
A 15m bearish bar inside a 4H+1H long is **not** a new short.

### 2.5 Alignment score is how we pick “the good trade”

Simple, honest scoring used in every MTF desk / TradingView confluence system:

Each frame: `+1` bull, `0` mixed, `-1` bear.

| Score | Meaning | Product |
|---|---|---|
| **+4** | Daily+4H+1H+15m all long | **A-momentum long** — only these fight for “best trade” |
| **+3** | Three agree, 15m still catching up | **WATCH long** — do not chase; wait for 15m trigger |
| **+2** | Daily+4H long, 1H still pulling back | **PULLBACK long** — the *good* entry, not a flip |
| **0 / mixed** | Frames fight | **NO TRADE** |
| **−3 / −4** | Mirror shorts | **A-momentum short** |

TradeAlgo-style backtests: +3 alignment crushes +1. Mixed is noise.

**Locked:** the Process headline “best trade” is the highest **alignment × location × persisted fuel** name.  
Not the highest LIS. Not the latest scan winner.

When two names are both +4, prefer:

1. Stronger 4H structure (clear HH-HL vs messy)  
2. 1H expansion (range of last 3 × 1H bars vs ATR) — *current* momentum  
3. Chain agrees (fresh buying / writing, not exhaustion)  
4. At a known level (put wall / VWAP / Cam S3 for longs)  
5. Not expiry-pin, not first 15 minutes  

That list **is** “which is the good trade.”

### 2.6 Chain comes *after* frames

TradeAlgo’s own options note: for a multi-day option, weekly/daily/4H pick call vs put; lower frame only improves fill.

For *our* intraday / same-day or 1–5 day holds:

1. Frames pick **CE vs PE** (side).  
2. Chain picks **whether institutions are actually funding that side**.  
3. 15m picks **when**.

If frames say long and chain says call writing + put buying → **NO TRADE**.  
Do not invent a short just because the chain is noisy. Frames still own the veto.

If frames say long and chain says put writing + fresh CE buying → this is the **correct momentum trade**.

### 2.7 You do not need a bias every name, every minute

Tradeciety: a valid output is **neutral**. Most of the F&O book will be mixed. The product should show 3–8 aligned names, not 40 “signals.”

---

## 3. Locked product design (what we would build later)

### 3.1 Object: `MTF Card` (per symbol, slow)

Computed from **closed** candles only (4H close, 1H close, 15m close). Never from a forming bar. This is the other half of “don’t change anytime.”

```
symbol
daily_bias     BULL / BEAR / MIXED
h4_bias
h1_bias
m15_bias
align_score    -4 … +4
align_label    FULL_LONG / PULLBACK_LONG / MIXED / …
structure      HH_HL / LH_LL / RANGE
momentum_now   EXPANDING / FLAT / COMPRESSING   (1H range vs ATR)
allowed_side   LONG | SHORT | NONE
next_review    next 1H close (or next 4H close if locked)
```

Refresh:

| Layer | Recalc when |
|---|---|
| Daily | Next day 9:14 |
| 4H | Each 4H close (IST 9:15, 13:15, …) |
| 1H | Each 1H close |
| 15m | Each 15m close — **trigger only**, does not rewrite `allowed_side` |

A 15m tick **cannot** change `allowed_side`. That is the whole point.

### 3.2 Pipeline (the plan you described)

```
FNO universe
    ↓
Score Daily + 4H + 1H  (strength board)
    ↓
Keep only |align| >= 2   (same-side Daily+4H at minimum)
    ↓
Read option chain + futures + walls   (fuel / veto)
    ↓
If fuel agrees → Candidate
    ↓
Wait for 15m trigger in that direction (7/20 reclaim, OR break, VWAP reclaim)
    ↓
Promote to CONFIRMED MOMENTUM TRADE
    ↓
Lock side until 1H/4H invalidation (section 2.4)
```

15m is observed **continuously** for *timing*.  
It is **not** a voter that can turn a long into a short.

### 3.3 What “confirmed” means (promotion checklist)

All of these, not 3 of 7:

1. Daily does **not** oppose (MIXED is ok; opposite is veto).  
2. 4H = the side.  
3. 1H = same side **or** a clean pullback that has started to turn (price back above 1H 20 for a long).  
4. Alignment ≥ +3 for “best trade” board ( +2 allowed as WATCH / pullback).  
5. Chain fuel agrees (Fresh CE buying or PE writing for longs; mirror for shorts).  
6. Not dual-side unusual.  
7. Location ≥ 4 (existing institutional levels).  
8. 15m **closed** trigger in direction (not a wick).  
9. Session gate (not opening 15m, not last 15m for *new* confirms).  
10. Persistence of fuel (already built) — still required.

Then the card says:

```
HDFCBANK    BULLISH MOMENTUM    CONFIRMED
4H HH-HL · 1H expanding · 15m 7>20
Fuel: Put writing 1660 + CE buying
Hold until: 1H close < 1648 (last HL) or 4H close < 20 EMA
```

That is the “good trade.”  
Everything else is tape.

### 3.4 How the board should feel

**One campaign per symbol.**  
HDFC long confirmed at 10:40 stays HDFC long until 1H/4H kill.  
A hotter RELIANCE can *join* the board. It does not steal HDFC’s side or delete HDFC.

**Sort key for “best”:**

```
rank = |align_score| × (1 + expanding) × location × persist × chain_agree
```

Show top 5 CONFIRMED.  
Then WATCH (+2 / waiting for 15m).  
Then tape.

**15m observation panel** (what you asked to “observe”):  
On the open idea, a small 15m strip: last 8 closes, 7/20 state, “trigger yes/no.”  
This is a *health light*, not a new signal generator.

### 3.5 Combine with what exists (do not rebuild)

| Keep | Change |
|---|---|
| Process lock + hysteresis | Promotion also requires MTF `allowed_side` |
| Pivots / Cam / CPR / walls | Still location votes |
| CE/PE matrix + LIS | Fuel only, after MTF |
| 7/200 first-cross | 15m *candidate* factory, still needs 4H/1H |
| Desk HTF gate | Becomes the Daily+4H `allowed_side` |
| Outcome jsonl | Add align_score, which frame killed it |

---

## 4. Worked example (so the idea is concrete)

**HDFCBANK**

- Daily: above 20 and 50, HH-HL → **BULL**  
- 4H: above 20, last two 4H higher lows → **BULL**  
- 1H: pulled back to 20 EMA, last 1H closes back above → **BULL turning**  
- 15m: 10:15 still below 7/20 → **not a trigger yet**  
  → Board: **WATCH LONG** (score +3). No CE buy yet.

- 10:45 15m **closes** back above 7 and 20, VWAP reclaim  
- Chain: 1660 PE writing + 1680 CE buying, futures long buildup  
- Spot at put wall + S1 cluster  

→ **CONFIRMED BULLISH MOMENTUM.** Buy 1680 CE. Stop under last 1H HL.

11:00 15m goes red and unstacks.  
**We do nothing to the side.** Trail or hold. Card still says BULLISH.

13:15 4H still green. Idea lives.

Next day 13:15 4H closes below 4H 20 and breaks the 4H HL.  
**Now** we kill. Not before.

A 11:05 RELIANCE +4 print can appear as a *second* confirmed long.  
It does not convert HDFC to “not the trade.”

---

## 5. What we will *not* do (so this doesn’t become another flicker engine)

1. No 5m voting.  
2. No “best LIS this scan” as the headline.  
3. No reversing a confirmed long into a short on PE prints.  
4. No using forming (unclosed) 15m/1H/4H bars.  
5. No requiring all 180 names to have a bias. Most should be silent.  
6. No adding more factors inside LIS. MTF is a **first stage**, chain is a **second stage**.  
7. No weekly/monthly in v1 of this product (rate limits + wrong horizon).  
8. No auto-size / auto-order. This is still a desk card.

---

## 6. Data / rate-limit reality (so the plan is honest)

A naive “fetch 4H + 1H + 15m for 180 names every scan” will melt Fyers quota.

**Decided approach:**

- Daily: already fetched for pivots (reuse).  
- 4H: fetch once, cache until next 4H close (~4 hours).  
- 1H: cache ~45–60 min (we already have history TTL).  
- 15m: we already pull this for 7/200 and tech_filters — **reuse**, do not double-call.  
- Full MTF score: only names that pass a cheap Daily+4H prefilter, or the radar candidate set.  
- Shared candle pool (`shared_universe` / market cache) is the right place.

If quota is tight: score MTF only for Process candidates + 7/200 hits, not the whole book. The *philosophy* stays top-down; the *universe* can be the already-interesting names.

---

## 7. Decisions locked (read these first)

1. **Top-down only.** Daily → 4H → 1H → 15m → chain.  
2. **4H owns allowed side.** 15m cannot flip it.  
3. **Confirmed means frames + chain + closed 15m trigger.** Not LIS alone.  
4. **Continue the direction until 1H structure or 4H bias breaks.**  
5. **“Good trade” = highest alignment among confirmed names**, then expansion, then fuel, then location.  
6. **Mixed frames = no trade.** Neutral is a valid, common output.  
7. **Closed candles only** for any frame that can change state.  
8. **Reuse existing process lock, levels, and CE/PE matrix.** This is a new *first stage*, not a rewrite.  
9. **Three voting frames + 15m trigger.** Not five charts.  
10. **Accuracy still needs the ledger** — log which frame promoted and which frame killed.

---

## 8. Suggested build order (later, after you say go)

1. Pure `mtf_engine.py`: bias per frame + align_score from candle lists (unit tests, no API).  
2. Cache 4H/1H next to existing 15m/daily.  
3. Attach `allowed_side` + `align_score` onto Process ideas.  
4. Promotion rule: cannot CONFIRMED if `allowed_side` conflicts.  
5. Invalidation: 15m cannot kill; 1H downgrades; 4H kills.  
6. UI: Process card shows `4H BULL · 1H BULL · 15m TRIGGER` and **BULLISH MOMENTUM** only when confirmed.  
7. Rank the board by alignment, not last-tick LIS.

---

## 9. Sources (for reread)

- Alexander Elder — Triple Screen (tide / wave / ripple; factor 4–6; different tool per screen)  
- Tradeciety — “How to perform a multi timeframe analysis”: top-down only; 4H+15m for fast intraday; 1H+15m for classic day trade; you do not always need a bias  
- TradeAlgo — multiple timeframe alignment; ~15–25% better than single-frame; 3 frames optimal; counter-HTF loses; day-trader stack Daily / 60m / 15m; options: HTF picks call vs put  
- Journal of Technical Analysis (cited) — two-frame alignment ~67% vs ~49% single-frame (treat as directionally useful, not a promise)  
- Bookmap / PrimeX / desk posts — 4H bias, 1H control, 15m confirm, lower = fill  
- Our files: `flow.md`, `7_200_cross.md`, `tech_filters.py`, `desk_decision.py`, `MTF` already hinted in HTF gate

---

## 10. Bottom line

You are right: a “good” trade is not the loudest option print.  
It is a name that is **strong on Daily + 4H + 1H**, whose **chain funds that same side**, whose **15m has just confirmed**, and that we **leave alone** until the *higher* frames fail.

15m is the camera we watch.  
4H is the map we obey.

If you want this built next, the first slice is the alignment score + “15m cannot flip a confirmed side.” That single rule is most of the “continue the direction” behaviour.
