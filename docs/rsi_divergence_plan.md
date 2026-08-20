# RSI Divergence — Implementation Plan

**Status:** IMPLEMENTED (2026-08-17). Detector + desk hook + radar badge.  
**Date:** 2026-08-17  
**Source spec:** `RSI_Divergence_README.md` (research)  
**Related:** `docs/rsi.md` (RSI extreme desk, R4), `docs/routingfix.md` (one harvest writer)

This is the *how and where*. The README is *what divergence is*. If they disagree, **this plan wins** after you confirm it.

---

## 0. One sentence

Add **classic RSI divergence** (price LL + RSI HL = long warning; price HH + RSI LH = short warning) as a **boost + tag** on the existing RSI desk and Flow Radar. It never opens a new Fyers loop, never prints a TRADE by itself, and never overrides 4H or option-chain gates.

---

## 1. What we are building / not building

### Building

- Confirmed-pivot bullish / bearish divergence on **stored 15m** and **derived 1H**.
- Event tags: `BULL_DIV` / `BEAR_DIV` / `*_FRESH` / `DIV_STALE`.
- Score boost on the RSI desk when a valid div is present.
- Badge + tooltip on Flow Radar rows (the page you actually use).
- Same fields on `RSIScanner` (exists, no nav) so the desk GET stays complete.
- Unit tests on synthetic LL/HL and HH/LH series.

### Not building

- A new “Divergence Scanner” page or Dashboard button.
- Hidden / reverse / regular divergence (v1 = classic only).
- 5m divergence (5m is not harvested; README priority D = ignore).
- Auto ingest into the idea book (rsi.md §12.7 stays no).
- A second harvest / Fyers history walk.
- Changing LIS, grade, or the process-trade formula.
- Using divergence as a buy/sell button.

README §2 and §14: divergence is a **momentum exhaustion warning**, not a scanner dump.

---

## 2. Locked decisions (precautions — do not reopen while coding)

| # | Decision | Lock |
|---|---|---|
| 1 | Data | Store `history.15` + `aggregate_ohlcv(..., 60)` only. No 5m. No Fyers. |
| 2 | RSI | Wilder 14 — reuse `rsi_wilder`. Do not fork a second RSI. |
| 3 | Pivots | Confirmed only: left=4, right=2. Forming bar cannot be a pivot. |
| 4 | Min gap | ≥ 5 closed bars between the two pivots. |
| 5 | Min RSI gap | ≥ 4 RSI points between the two RSI pivots. Else ignore (kills micro noise). |
| 6 | Zone | Second RSI pivot must be ≤ 38 (bull) or ≥ 62 (bear). Mid-range 40–60 → IGNORE even if price diverged. |
| 7 | Fresh | `bars_ago` of the **recent** pivot ≤ 3 → `*_FRESH`. |
| 8 | Stale | Recent pivot `bars_ago` > 8 → `DIV_STALE`. Boost dies. Do not list as a live div. |
| 9 | TRADE | **Never** from divergence alone. TRADE still needs existing extreme desk rules: reclaim (or P≥75) + OC agrees + 4H not opposite. Div only **boosts E** and **tags the ticket**. |
| 10 | WATCH extra | Valid 15m div + RSI ≤38 / ≥62 + OC not conflicting + 4H not opposite, but no reclaim yet → WATCH (even if not classic 30/70). |
| 11 | 4H | Same `mtf_gate`. Bull div + 4H firmly SHORT → REJECT long. Bear div + 4H firmly LONG → REJECT short. |
| 12 | OC | Same `permission_from_snapshot`. Bull div + bearish/conflict chain → REJECT (knife). Bear div + bullish chain → WATCH momentum, not a fade. |
| 13 | Radar | Div is a **weight + badge**, not a new column board. Do not rewrite LIS/grade. |
| 14 | Idea book | No auto ingest. |
| 15 | Hidden div | Out of v1. |
| 16 | Scoring when no div | Keep today’s `desk_score = 0.40E + 0.60P`. Do **not** change names that have no divergence. |

---

## 3. How detection works (logic)

Run on **closed** 15m bars (drop the forming bar, same idea as `mtf_engine.closed_candles`). Derive 1H from those 15m bars. Compute Wilder RSI(14) once.

### 3.1 Pivots

On price:

- Swing low: bar low is strictly below `left` neighbours and not above `right` neighbours.
- Swing high: mirror.

On RSI:

- Same fractal on the RSI series (not on price).
- Align by **bar index**, not by matching timestamps after the fact.

Only indices `i` where `left <= i <= n-1-right` are allowed. That is the anti-repaint rule.

Keep the last ~8 swing lows and last ~8 swing highs. Compare **the last two** of the same type.

### 3.2 Bullish divergence (`BULL_DIV`)

Let `L1` be the older swing low, `L2` the newer.

```
price[L2] < price[L1]          # price lower low
rsi[L2]   > rsi[L1]            # RSI higher low
L2 - L1   >= 5                 # bars
rsi[L2] - rsi[L1] >= 4         # RSI gap
rsi[L2]   <= 38                # still exhausted, not mid-range
bars_ago(L2) <= 8              # else DIV_STALE / drop
```

Side implied: **BULLISH** (bounce warning).

### 3.3 Bearish divergence (`BEAR_DIV`)

```
price[H2] > price[H1]
rsi[H2]   < rsi[H1]
H2 - H1   >= 5
rsi[H1] - rsi[H2] >= 4
rsi[H2]   >= 62
bars_ago(H2) <= 8
```

Side implied: **BEARISH** (fade warning).

### 3.4 1H

Same function on aggregated 60m candles. Used only as **confirm / oppose**, never as the only trigger.

| 1H vs 15m | Meaning |
|---|---|
| Same type | Priority A — extra D points |
| No 1H div | Priority B/C — 15m still valid |
| Opposite type | Opposed — no 1H bonus; do **not** auto-REJECT 15m (4H gate still owns veto) |

### 3.5 Event payload (every call returns this or empty)

```
{
  type: BULL_DIV | BEAR_DIV | None
  tf: 15 | 60
  fresh: bool            # bars_ago <= 3
  stale: bool            # bars_ago > 8
  bars_ago: int          # of the recent pivot
  price_l1, price_l2
  rsi_l1, rsi_l2
  bar_l1, bar_l2
  rsi_gap: float
}
```

If both a bull and a bear could fire (should be rare with zone filters), take the one whose recent pivot is **newer**. If tied, take none (conflict).

---

## 4. Where it plugs in (do not wander)

```
harvest book (already there)
        │
        ▼
rsi_wilder(15m) + aggregate 60m + rsi_wilder(60)
        │
        ▼
NEW  detect_rsi_divergence(candles, rsi_series)     ← pure, testable
        │
        ├─ evaluate_symbol()      RSI desk TRADE/WATCH/REJECT
        ├─ rsi_snapshot()         cheap read for radar
        └─ weight_radar_row()     Flow Radar desk_score + badge
```

### 4.1 New file (detection only)

`backend/app/services/strategies/rsi_divergence.py`

Functions:

- `closed_bars(candles)` — drop forming 15m bar
- `detect_pivots(series, left=4, right=2, kind=low|high)`
- `detect_bullish_divergence(price_lows, rsi_series)`
- `detect_bearish_divergence(price_highs, rsi_series)`
- `classify_divergence(candles, rsi_series) -> dict`

No Fyers, no store, no permission, no UI. This file is the detector.

### 4.2 Hook: RSI desk — `rsi_desk.py`

**`evaluate_symbol`** after `rsi_wilder` / `classify_rsi_event`:

1. `div15 = classify_divergence(m15, r15s)`
2. `div60 = classify_divergence(h1, r60s)` if 1H exists
3. If `div15.type` is bullish and current side would have been MID: **set side BULLISH** only when `rsi15 <= 38` (WATCH path, not TRADE).
4. Mirror for bearish / `rsi15 >= 62`.
5. Pass `div15` / `div60` into `_extreme_score` and `_classify_board`.
6. On TRADE ticket, append event to `ticket["trigger"]` (do not reuse 7/200 wording).

**`_extreme_score` boost** (README §6.1), only if div is not stale:

```
+15  if 15m BULL_DIV and side is BULLISH (or BEAR_DIV and BEARISH)
+10  if 1H same type
+5   if rsi15 ≤ 35 (bull) or ≥ 65 (bear)
+0   if stale or type fights the side
```

Cap E at 100 as today.

**`desk_score` precaution:**

```
if valid live 15m div:
    desk = 0.35*E + 0.25*D + 0.40*P
else:
    desk = 0.40*E + 0.60*P          # unchanged
```

`D` (0–100) from README §8, computed in `rsi_divergence.py` as `divergence_score(div15, div60, rsi15, near_vwap)`.

**`_classify_board` extra branches** (order matters — keep existing hard gates first):

1. Existing: 4H hard → REJECT  
2. Existing: OC conflict / futures opposite → REJECT  
3. Existing: sponsored OB + bullish chain → WATCH (do not fade)  
4. **New:** live div + zone MID + rsi in ≤38/≥62 + OC ok → **WATCH** `"divergence, wait reclaim"` instead of today’s `"RSI not extreme"` reject  
5. Existing: P < 40 → REJECT  
6. Existing: TRADE only if reclaim (or P≥75) and E≥55  
7. Div does **not** skip reclaim. README §9 row 1 still needs reclaim for TRADE.

**`scan_book`:** stop dropping every MID row. If `div` is live and board is WATCH, keep the row. Still drop true mid-range IGNORE (no extreme, no div).

**`rsi_snapshot`:** add `div_type`, `div_tf`, `div_fresh`, `div_bars_ago`, `div_rsi_gap` so radar does not re-run two detectors.

### 4.3 Hook: Flow Radar — `weight_radar_row` (same file)

After `rsi_snapshot`:

| Radar direction vs 15m div | Effect |
|---|---|
| Agrees (long + BULL_DIV, short + BEAR_DIV) | `rsi_w += 8`, +4 if 1H same, +4 if fresh |
| Fights | `rsi_w -= 10` |
| Stale / none | 0 |

Hard caps already on the row (4H hard ≤38, OC conflict ≤42, VWAP fight ≤50) **stay**. Divergence cannot punch through them.

Set `row["rsi_div"]`, `row["rsi_div_fresh"]`, `row["rsi_div_bars_ago"]`.

Do **not** flip `desk_align` to STACK just because of divergence. STACK/BOUNCE remains the RSI-extreme + OC path. Div is a badge on FLOW/STACK/FIGHT.

### 4.4 Hook: UI

**`frontend/components/OptionFlowRadar.tsx`** (primary)

- On the existing RSI 15/60 cell: badge `BULL DIV` (emerald) / `BEAR DIV` (rose).
- Fresh: brighter / `FRESH`.
- `title` tooltip: `15m price 407→401 · RSI 27→31 · 2 bars ago`.
- Detail pane: one line under RSI.

**`frontend/components/RSIScanner.tsx`** (desk GET, no new nav)

- Column or badge on TRADE/WATCH rows.
- Ticket panel shows event + pivot numbers.

**`frontend/lib/api.ts`** — no new endpoints. Same `GET /strategies/rsi/scan` and harvest-weighted radar rows.

### 4.5 Harvest (optional, not required for v1)

Do **not** add a writer pass. Detector is CPU on read (15m×40d is cheap). If harvest later writes `derived.rsi_div`, that is a polish, not this plan.

### 4.6 Files we will not touch

- `idea_engine.py`, `idea_book.py` (no ingest)
- `radar_signal_engine.py` LIS/grade
- `fyers_market.py`, harvest writer loop
- `mtf_engine.py` (reuse gate only)
- VAT / 7/200 scanner logic

---

## 5. Board truth table (so we do not get confused)

| 15m | 1H | RSI zone | Reclaim | OC | 4H | Board |
|---|---|---|---|---|---|---|
| BULL_DIV | same / none | ≤30 or reclaim | yes | bullish | not SHORT | **TRADE** (existing path + boost) |
| BULL_DIV | any | ≤38 | no | bullish | not SHORT | **WATCH** |
| BULL_DIV | any | any | any | bearish / conflict | any | **REJECT** knife |
| BULL_DIV | any | any | any | any | firmly SHORT | **REJECT** |
| BULL_DIV | any | 40–60 | — | — | — | **IGNORE** (no row) |
| BEAR_DIV | any | ≥70 or reclaim | yes | bearish | not LONG | **TRADE** |
| BEAR_DIV | any | ≥62 | no | bearish | not LONG | **WATCH** |
| BEAR_DIV | any | ≥70 | any | bullish OC | any | **WATCH** strength — do not fade |
| none | — | — | — | — | — | today’s desk, unchanged |
| 5m only | — | — | — | — | — | never computed |

---

## 6. Tests (required before calling it done)

New: `backend/app/services/strategies/test_rsi_divergence.py`

| Case | Expect |
|---|---|
| Synthetic price LL + RSI HL, 6 bars apart, RSI 28 then 33 | `BULL_DIV`, not stale |
| Same but last pivot is the forming bar | no pivot / no div |
| Pivots 3 bars apart | no div |
| RSI gap 2 points | no div |
| Second RSI low at 52 | IGNORE (mid) |
| bars_ago 10 | stale / no live boost |
| Price HH + RSI LH, RSI 72 then 64 | `BEAR_DIV` |
| `evaluate_symbol` with mocked store: bull div + 4H SHORT | REJECT, no ticket |
| bull div + OC conflict | REJECT |
| no div | `desk_score` formula unchanged (0.40E+0.60P) |

No live Fyers in tests.

---

## 7. Build order (when you say implement)

1. `rsi_divergence.py` + tests (detector green first).  
2. Wire `evaluate_symbol` / `_extreme_score` / `_classify_board` / `scan_book` / `rsi_snapshot`.  
3. Wire `weight_radar_row` (badge fields + modest weight).  
4. Flow Radar badge + tooltip.  
5. RSIScanner badge + ticket line.  
6. Re-run divergence tests + existing `test_vwap_oc_process.py` (must still pass).

Estimated surface: **two backend files + two frontend files + tests**. No new route.

---

## 8. Acceptance

1. Opening Flow Radar or RSI GET does not call Fyers for divergence.  
2. A name with only a pretty divergence and RSI at 50 does **not** appear as a trade or a radar STACK.  
3. Oversold + reclaim + bullish OC + 4H not short still TRADEs; if a bull div is also there, E/desk is higher and the ticket says `BULL_DIV`.  
4. Bull div + 4H firmly short never prints a long ticket.  
5. Bear div + bullish chain is not sold as a short.  
6. Radar rows show a div badge only when 15m div is live (not stale).  
7. Names with no divergence keep the old desk_score mix.

---

## 9. Confirm before coding

Reply with **go** (or edit this file) if these five are acceptable:

1. **No new page** — Radar badge + existing RSI desk GET only.  
2. **Divergence never TRADEs alone** — reclaim/P≥75 + OC + 4H still required.  
3. **WATCH** allowed for live div in the 38/62 band while waiting reclaim.  
4. **No 5m, no idea-book ingest, no harvest writer change.**  
5. **Score mix changes only when a live 15m div exists.**

Once confirmed, implement in the order in §7 and do not expand scope.

---

*End of plan. No application code was changed for this document.*
