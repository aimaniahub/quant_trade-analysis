# AI-SYSTEM — News → F&O shortlist → option-chain follow

**Date:** 29 August 2026  
**Status:** Research + implementation spec only. **No code in this pass.**  
**Depends on:** `quantopt.md` (chain events, explode vs tradeable, GEX as context), `PROJECT_REPORT.md` (one Radar, harvest-only writer).  
**News source (this repo):** `whalesbook/` — scraped dump from [whalesbook.com/market-news](https://www.whalesbook.com/market-news/English/all). Treat the scraper as **done**. This file is the analysis layer that does not exist yet.

---

## 0. The actual problem (not “add ChatGPT”)

OptionGreek can harvest ~187 F&O chains. It does **not** know *why* a name should move today.

Whalesbook can ingest a large news firehose. It does **not** know which of those headlines are:

- F&O-tradable,
- **intraday**-relevant,
- not already in the price,
- concentrated enough that an option chain can confirm them.

Current `news_context.py` only asks Grok for a **market BIAS** (BULLISH/BEARISH/NEUTRAL). That is a weather report. It does not pick stocks, does not map tickers, does not read a chain.

Your idea is correct **if and only if** the jobs are split:

```
NEWS (scraper)     →  what happened
AI (OpenRouter)    →  which F&O names are plausibly movable *today*  (WATCHLIST of 5)
CHAIN (our radar)  →  is unusual money actually in the options? which strike?  (EVENT)
LOGICS (quantopt)  →  intent + futures confirm + trade or wait  (TRADE / NO TRADE)
```

**Illegal collapse (do not build):**

```
NEWS → AI says BUY RELIANCE 1400 CE → we trade it
```

That is the same junk as tagging every stock `OI VOL SUP RES`. The model is guessing. The chain is the only instrument book we have.

This matches the previous production filter:

> EVENT → INTENT → CONFIRMATION → TRADE  
> never EVENT → BUY

News is **not** an event in the option book. News is a **priority signal**: “watch these five names harder.” The option print is the event.

---

## 1. What we already have vs what we do not

| Piece | Where | Status |
| :--- | :--- | :--- |
| News firehose | `whalesbook/README.md` dump + site `whalesbook.com` | Scraper considered **done**. Output = title, time IST, category, URL, 2–4 sentence body. |
| F&O universe | `backend/app/services/fno_stocks.py` | ~187 `NSE:SYMBOL-EQ` + indices. **Hard allow-list.** |
| Chain harvest | Radar, ~180s, store-first | Whole book. Do not start a second Fyers scanner. |
| Chain engine | `chain_anomaly` / `chain_desk` + `quantopt.md` | Structure + flow + futures. Must stay the trade brain. |
| “AI news” today | `news_context.py` → xAI Grok | Macro bias only. Unused as a stock picker. |
| Outcome log | `backend/app/data/idea_outcomes.jsonl` | Exists as a stub path. **Must become the news+chain lab.** |
| OpenRouter | not wired | To add as the **news NLP** client, not as the broker. |

**Where does “the system get news”?**  
It does **not** get it from Fyers. It does not need OpenRouter web-search. It gets it from the **Whalesbook scrape** you already run. The AI never browses. It only reads **our** article objects.

---

## 2. Honest read of the Whalesbook dump (why naive top-5 fails)

The 25 Jun 2026 sample in `whalesbook/README.md` is typical aggregator output. Classify it **before** any LLM:

| # | Headline (short) | Intraday F&O fuel? | Why |
| :--- | :--- | :--- | :--- |
| 1 | BDL ₹1,348 Cr HAL order + GS Sell | **Maybe** | Company-specific order. Need: is BDL in F&O? already gapped? chain alive? |
| 2 | RBI e-fraud liability 2027 | No (stock) | Policy, 2027. At most **BANKNIFTY** context, not a 5-name list. |
| 3 | ₹19,700 Cr carbon capture plan | Weak | Sector theme (steel/cement/power). Multi-name, slow. |
| 4 | Bollywood casting South stars | **Drop** | Not F&O, not a day trade. |
| 5 | TVS moves Norton production to India | Weak/maybe | Operational, not a 9:15 shock unless TVS is F&O and gap exists. |
| 6 | Noel Tata board retirements Nov | **Drop** | Dated, governance. |
| 7 | NBFC upper-layer rules | Weak | Sector. |
| 8 | Wealth mgmt $1.7T by 2030 | **Drop** | Research fluff. |
| 9 | ITR refund 7–10 days | **Drop** | Retail tax, not a ticker. |
| 10 | Fairfax / IDBI / CSB | Maybe sector | M&A. Only if names are F&O. |
| 11 | Crude down, Nifty > 24,000 | **Index** | Macro. Watch NIFTY/BANK, not five random stocks. |
| 12 | Ambika Cotton / Aether / Pearl Global technicals | **Drop** unless F&O | Brokerage on often non-F&O names. |
| … | Ex-dividend lists, IPO, MSME essay | **Drop** | Calendar / unlisted / essay. |

**Lesson:** ~70% of a “large news source” is **not** an intraday option candidate. If you send the raw 100 items to an LLM and say “pick top 5 movable stocks,” it will invent tradable stories from Bollywood and 2030 research. That is not analysis.

**Genuine path = filter first, model second.**

---

## 3. Doctrine (hard rules)

1. **AI never invents a ticker.** Every symbol must be linked from the article by a **deterministic alias map** (or an extractor whose output is then **checked** against that map). If the map misses, the name is skipped, not guessed.
2. **AI never invents a strike.** Strikes, walls, ΔOI, volume, GEX come from Fyers harvest + `chain_desk`. The model may *narrate* a card the engine already produced.
3. **Only F&O, not banned, not illiquid.** Intersection with `FNO_STOCKS` / harvest universe. If BDL is not in the F&O list, the HAL order is **cash/news only**.
4. **News creates WATCH, not TRADEABLE.** Pipeline from `quantopt.md` is unchanged: EVENT → INTENT → CONFIRMATION → TRADE. News is an input to **which names we follow more carefully**, not a buy.
5. **Macro ≠ single stock.** Crude, RBI, GIFT Nifty, US-Iran → `INDEX_CONTEXT` (NIFTY / BANKNIFTY / VIX). Do not pad the top-5 with RELIANCE + ONGC + BPCL because oil moved. Those three may be added as a **sector bucket**, separate from the five **idiosyncratic** names.
6. **Freshness is a gate.** Intraday options care about *today’s open and the next 3 hours*, not a 2027 rule or a November retirement.
7. **Already-priced is a gate.** If the article is from 8:00 IST and the stock already gapped 4% in pre-open / first 15 minutes *without* remaining expected-move, the news is **stale as a catalyst**. Still useful as *why the chain is busy*.
8. **OpenRouter is a contractor.** Structured JSON in, structured JSON out. Temperature low. Schema strict. Fallback models. **Code validates every field.**
9. **Measure outcomes.** Same missing layer as `quantopt.md` §5: did the five names move? did the chain confirm? did the trade (if any) work?

---

## 4. System architecture

```
                    ┌──────────────────────────────┐
                    │  Whalesbook scraper (done)   │
                    │  articles: id, ts, cat, url, │
                    │  title, body                 │
                    └────────────┬─────────────────┘
                                 │ new/changed ids
                                 ▼
                    ┌──────────────────────────────┐
                    │  N0  INGEST + DEDUPE         │
                    │  hash(url), IST ts, ttl 24h  │
                    └────────────┬─────────────────┘
                                 ▼
                    ┌──────────────────────────────┐
                    │  N1  HARD PREFILTER          │
                    │  drop IPO/essay/ex-div fluff │
                    │  keep order/earnings/rating/ │
                    │  m&a/policy/commodity/index  │
                    └────────────┬─────────────────┘
                                 ▼
                    ┌──────────────────────────────┐
                    │  N2  ENTITY LINK (code)      │
                    │  alias dict + optional LLM   │
                    │  extract → validate vs FNO   │
                    └────────────┬─────────────────┘
                                 ▼
                    ┌──────────────────────────────┐
                    │  N3  OPENROUTER RANK         │
                    │  only linked F&O candidates  │
                    │  score same-day option fuel  │
                    │  output: 5 names + reasons   │
                    └────────────┬─────────────────┘
                                 ▼
                    ┌──────────────────────────────┐
                    │  N4  CODE SANITY             │
                    │  FNO, ban, age, max 5,       │
                    │  no dup, sector vs idio      │
                    └────────────┬─────────────────┘
                                 ▼
              ┌──────────────────┴──────────────────┐
              ▼                                     ▼
     FOCUS WATCHLIST (5)                    INDEX CONTEXT
     priority harvest / follow              NIFTY BANK VIX
              │
              ▼
     ┌────────────────────────────┐
     │  C1  CHAIN DESK            │
     │  existing harvest +        │
     │  quantopt events           │
     │  EARLY / CONFIRMED explode │
     └────────────┬───────────────┘
                  ▼
     ┌────────────────────────────┐
     │  C2  FUSE                  │
     │  news_why + chain_card     │
     │  news cannot override veto │
     └────────────┬───────────────┘
                  ▼
     ┌────────────────────────────┐
     │  C3  OPTIONAL NARRATOR LLM │
     │  explain the card in prose │
     │  no new numbers            │
     └────────────┬───────────────┘
                  ▼
     Radar UI: “News focus 5”
     + same bull/bear/filter pane
     + outcome logger
```

Harvest stays **one writer**. The five names are a **priority overlay** (always in top-tier of the existing harvest), not a second 200/min Fyers loop.

---

## 5. Layer N1 — prefilter (no AI)

Drop before tokens are spent. Use category + keyword rules on title/body.

**Drop classes**

- Essays / 2030 outlook / “investors should note”
- IPO of unlisted names
- Tax/ITR/process explainers
- Ex-dividend *lists* of 17–45 names (calendar, not a move)
- Pure technical “stocks in focus” roundups that name non-F&O
- Sports / entertainment / lifestyle unless a listed F&O media name is explicit
- Duplicate URLs / same title within 6 hours

**Keep classes (event taxonomy)**

| `event_type` | Examples from dump | Typical option implication |
| :--- | :--- | :--- |
| `ORDER_WIN` | BDL HAL ₹1,348 Cr | Gap + fade or trend; chain tells which |
| `EARNINGS` | CCL Products FY26 profit +25% | IV rich; often **vol** not direction until chain |
| `RATING` | GS Sell on BDL, Motilal Buy Kotak | Weak unless size + liquid |
| `M_AND_A` | Fairfax / IDBI | Binary; only F&O names |
| `MGMT` | Noel Tata boards | Usually drop unless sudden CEO |
| `POLICY_STOCK` | NBFC rules hitting a named NBFC | Sector or one name |
| `MACRO_INDEX` | Crude, RBI stance, GIFT Nifty | Index context only |
| `COMMODITY` | Oil, gold | Map to **index + a sector bucket**, not 5 random |
| `LEGAL` | Adani US case | Named F&O only |
| `GUIDANCE` | Capex, production shift (TVS Norton) | Slow unless number is huge vs revenue |

If after N1 fewer than 8 articles remain, **do not force 5 stocks**. 2 real names beat 5 padded names.

---

## 6. Layer N2 — connecting news to specific stocks (the hard part)

This is the problem you named. LLMs are bad at it unless constrained.

### 6.1 Canonical alias table (source of truth)

Build `news_aliases.json` (code-owned, versioned):

```
"bharat dynamics" → NSE:BDL-EQ
"bdl"             → NSE:BDL-EQ
"tvs motor"       → NSE:TVSMOTOR-EQ
"kotak mahindra"  → NSE:KOTAKBANK-EQ
"hdfc bank"       → NSE:HDFCBANK-EQ
"tcs"             → NSE:TCS-EQ
"tata consultancy"→ NSE:TCS-EQ
...
```

Include group maps:

```
"tata group"  → [TCS, TATAMOTORS, TATAPOWER, TATASTEEL, TITAN, TRENT, ...] ∩ FNO
"adani"       → [ADANIENT, ADANIPORTS, ADANIGREEN, ...] ∩ FNO
```

Group hits are **sector/watch**, not automatic top-5. A Tata-boards story is not a TCS long.

**Indices**

```
nifty, nifty 50, sensex → NSE:NIFTY50-INDEX
bank nifty, nifty bank  → NSE:NIFTYBANK-INDEX
india vix, vix          → NSE:INDIAVIX-INDEX
```

If the linked symbol is **not** in `FNO_STOCKS`, attach `cash_only: true` and **exclude from the five**.

### 6.2 Extraction (OpenRouter, structured)

For each kept article, model returns **only** what the text supports:

```json
{
  "article_id": "6a3ca074...",
  "event_type": "ORDER_WIN",
  "horizon": "INTRADAY" | "SWING" | "STRUCTURAL" | "IRRELEVANT",
  "direction_hint": "BULLISH" | "BEARISH" | "VOL" | "UNCLEAR",
  "entities": [
    {
      "raw": "Bharat Dynamics",
      "role": "subject",
      "confidence": 0.9
    }
  ],
  "magnitude": {
    "kind": "ORDER_INR_CR",
    "value": 1348,
    "vs_unknown": true
  },
  "already_qualified": false,
  "why": "HAL order 1348 cr; GS still Sell"
}
```

Then **code** maps `entities[].raw` → alias table → `NSE:…`. If no alias hit: **discard entity**. Do not let the model output `NSE:BDL-EQ` as a free string (it will hallucinate `NSE:BHARATDYNAMICS-EQ`).

`horizon=STRUCTURAL|IRRELEVANT` never enters the five.

`direction_hint` is **not** a trade. GS Sell + order win is `UNCLEAR` or mixed. The chain decides.

### 6.3 Magnitude sanity (so “₹1348 Cr” is not always huge)

Without revenue/market-cap context, every crore figure looks like a bomb.

Store a static-ish table (refresh monthly) per F&O name: `mcap_cr`, `ttm_revenue_cr`. Score:

```
order_ratio = order_cr / max(ttm_revenue_cr, 1)
```

- `< 2%` of revenue → noise for **intraday options**
- `2–10%` → watch
- `> 10%` or `> 5% of mcap` → high fuel

If we lack fundamentals, `magnitude.vs_unknown = true` and **cap the news score** (cannot be #1 on a number alone).

---

## 7. Layer N3 — OpenRouter ranks the *already-linked* F&O set

### 7.1 Why OpenRouter (and how to use it)

OpenRouter = OpenAI-compatible `POST https://openrouter.ai/api/v1/chat/completions`, one key, many models, **structured outputs** (`response_format.json_schema`, `strict: true`).

Use it for **NLP + ranking**, not for chain math.

| Job | Model class | Why |
| :--- | :--- | :--- |
| N2 extract per article | cheap, JSON-reliable (e.g. Gemini Flash / GPT-4.1-mini class via OpenRouter) | Volume of articles |
| N3 rank to 5 | stronger, still JSON (Claude Sonnet / GPT-4.1 / Gemini Pro class) | Judgement among 10–30 candidates |
| C3 narrator | cheap | Prose around a frozen card |

**Provider routing:** `require_parameters: true` so only endpoints that honor `json_schema` are used. Temperature `0–0.2`. Max tokens bounded. Timeout 20s. Retry once on another model.

**Do not enable OpenRouter web search / plugins for this path.** We already have the corpus. Web search reintroduces unsourced tickers.

**Do not send the whole chain** (40 strikes × greeks) into the ranker. Ranker sees news + **tiny market snapshot** (spot %, gap, whether harvest already flags explode). Chain detail is C1.

### 7.2 Ranker input (code-assembled)

For each linked F&O candidate:

```
symbol, name
articles: [{title, event_type, ts_ist, why, direction_hint, magnitude}]
market: {gap_pct, last_ret_15m, harvest_grade, explode_early: bool}  // if known
fno: {in_universe: true, banned: false, bucket: HEAVY|REST}
```

Plus index context: Nifty chg, VIX chg, crude if present.

### 7.3 Ranker output schema (strict)

```json
{
  "asof_ist": "2026-06-25T09:05:00+05:30",
  "index_context": {
    "bias": "RISK_ON" | "RISK_OFF" | "MIXED",
    "why": "crude down, GIFT green",
    "follow": ["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"]
  },
  "picks": [
    {
      "symbol": "NSE:BDL-EQ",
      "rank": 1,
      "news_score": 0.78,
      "horizon": "INTRADAY",
      "news_intent": "BULLISH" | "BEARISH" | "VOL" | "UNCLEAR",
      "event_types": ["ORDER_WIN", "RATING"],
      "article_ids": ["6a3ca074..."],
      "why": "large defence order; rating still Sell — chain must resolve",
      "risks": ["already in price", "GS Sell"]
    }
  ],
  "rejected": [
    {"symbol": "NSE:TVSMOTOR-EQ", "reason": "operational, not same-day catalyst"}
  ]
}
```

`picks.length <= 5`. `symbol` **must** be copied from the input list (prompt + schema enum if the set is small enough; otherwise code-check).

`news_score` is the model’s **same-day option-relevance**, not “quality of journalism.”

### 7.4 What “intraday movable” means (prompt law)

The ranker is instructed to prefer names where **all** hold:

1. Catalyst is **company-specific** or a **tight sector** (not “India GDP”).
2. Horizon is **hours**, not years.
3. Magnitude is large vs the company **or** the event is binary (legal/M&A).
4. Name is liquid F&O (we already filtered).
5. Direction may be UNCLEAR — **VOL is a valid pick** (earnings, mixed order+sell rating).

It is instructed to **demote**:

- already-moved > 0.8 × typical daily range with no remaining EM,
- 20-name “stocks in focus” laundry lists,
- rating-only on a quiet name,
- duplicate stories of the same symbol (collapse, don’t occupy 2 of 5 slots).

---

## 8. Layer N4 — code sanity (the model is not trusted)

After every LLM call:

```
for pick in picks:
    assert pick.symbol in input_symbols
    assert pick.symbol in FNO_STOCKS
    assert not banned(pick.symbol)
    assert pick.horizon == "INTRADAY"
    assert pick.article_ids ⊆ ingested
    assert alias_link_exists(pick.symbol, pick.article_ids)
drop extras after 5
dedupe by symbol
if index_context.follow: do not count NIFTY/BANK inside the 5 unless no idio names
```

If the model returns `NSE:BHARAT-DYNAMICS-EQ`, it dies in N4. We log the miss and fix the alias table — we do **not** “fuzzy match” into a trade.

---

## 9. Connecting to **our** option chain (C1–C2)

This is where OptionGreek actually lives.

### 9.1 Follow, don’t refetch the universe

Radar already harvests the book every ~3 minutes. For the five:

- Pin them in **top-tier** of `build_harvest_priority` so they are never skipped.
- Optional: **one extra chain refresh** for a name only when N3 just promoted it (still through the same rate limiter). Never a parallel scraper.
- Store `news_focus = {symbol, news_score, news_intent, article_ids, ts}` on the board row.

UI: a “News focus” strip of 5, **separate** from Bull/Bear. Clicking a name opens the same chain desk as today.

### 9.2 Fuse table (news cannot override chain)

| News intent | Chain event (`quantopt`) | Futures | Output |
| :--- | :--- | :--- | :--- |
| BULLISH | BUY_CE / WRITE_PE + agree | LONG_BUILD | Candidate **long** card (engine) |
| BULLISH | BUY_CE | SHORT_BUILD | **WATCH / NO TRADE** — news and futures fight |
| BULLISH | WRITE_CE at call wall | any | **Do not buy CE into the wall** |
| BULLISH | PIN / QUIET | any | **WATCH** — story without prints |
| BEARISH | BUY_PE / WRITE_CE + agree | SHORT_BUILD | Candidate **short** card |
| VOL | VOL_EXPLODE / both wings | any | **No direction**; maybe defined-risk vol — default WAIT for v1 |
| UNCLEAR | EXPLODE EARLY | — | Follow; no TRADEABLE |
| any | nothing hot after 2–3 harvests | — | **Decay** the news score; drop from 5 if a better name appears |

This is the same law: **EXPLODE ≠ TRADEABLE.** News-BULLISH + EXPLODE + futures short = interesting, not a long.

### 9.3 Strike recommendation (engine only)

The user wants “then recommends the strike.” That recommendation is **`chain_desk.build_trade_card`**, not the LLM.

Inputs the engine already has / `quantopt` specifies:

- live wall / ATM / 0.15–0.45 delta band
- remaining expected move (ATM straddle)
- DTE (stock monthlies vs index weeklies)
- writing vs buying at the hot cluster
- lot size / liquidity of that strike (volume + OI)

**v1 rule:** if the engine would not issue a card, the UI shows:

```
NEWS: BDL order 1348 Cr (watch)
CHAIN: QUIET / PIN / CONFLICT
ACTION: no strike
```

Never “AI suggests 1400 CE” with empty volume.

### 9.4 Optional narrator (C3)

Second LLM call **after** the card is frozen:

```
You are given ONLY this JSON card and these article titles.
Write ≤ 80 words. Do not add strikes, prices, or facts not in the JSON.
If action is WAIT, say wait.
```

If the narrator emits a new strike, **discard the prose**.

---

## 10. Clocks (when the five are rebuilt)

| Clock | When | Why |
| :--- | :--- | :--- |
| **Pre-open batch** | 08:20–09:10 IST | Most Whalesbook items in the dump are 08:00–09:00. Rank five **before** the bell. |
| **Open pulse** | 09:20, 09:35 | Drop names that already spent the move; promote if chain EARLY-EXPLODE aligns. |
| **Intraday incremental** | every 10–15 min **or** on N new articles | Do not rerank 5 every harvest (jitter). Sticky unless score gap > 0.15 or chain conflict. |
| **Expiry / last 90 min** | special | News almost irrelevant vs gamma/pin (`quantopt` max-pain window). Freeze new promotions. |

3-minute harvest still applies: **EARLY EXPLOSION** vs **CONFIRMED**. News can put a name on EARLY watch; confirmation is still OI/volume persistence.

---

## 11. What OpenRouter must never see / never decide

**Never see**

- Fyers access tokens
- Full 187-name chains every cycle (token + leakage)
- Order placement tools

**Never decide**

- TRADEABLE / QUIET grade
- Strike, stop, target
- Futures state
- GEX sign as fact

GEX remains **regime context** inside the chain engine (`quantopt` caution #3). The LLM may be told `gex_regime: POSITIVE|NEGATIVE|UNKNOWN` as a word, not as “dealers will buy.”

---

## 12. Data contracts

### 12.1 Article (from scraper)

```
id, url, ts_ist, category, title, body, source="whalesbook"
```

### 12.2 Linked candidate (after N2)

```
symbol, name, article_ids[], event_types[], direction_hint, horizon, magnitude, cash_only
```

### 12.3 News focus row (on the board)

```
symbol, rank, news_score, news_intent, why, article_ids, ts_rank, sticky_until
```

### 12.4 Fused idea (logged)

```
idea_id, ts_detect
news: {intent, score, event_types, article_ids}
chain: {grade, explode_state, intent, flags, strike?, setup_score, gex_regime}
futures: {state}
spot: {px, gap_pct, em_remaining}
action: WAIT | WATCH | CARD
```

### 12.5 Outcome (the missing quant layer — required)

At 5m / 15m / 30m / 60m / EOD:

```
und_ret, opt_ret (if card), mfe, mae
chain_confirmed: bool          # EARLY → CONFIRMED
wall_broke: bool
still_in_top5: bool
```

Questions this answers after 30 sessions:

- Did news-top-5 names outperform a random 5 from the harvest on 30m |return|?
- Conditional: news-BULLISH ∩ chain-BUY_CE ∩ futures-LONG → continuation rate?
- How often did news-top-5 stay QUIET (wasted attention)?
- Did OpenRouter rank correlate with realized |move| or only with headline drama?

If news-top-5 is no better than harvest explode_score top-5, **the AI layer is optional** and we should not pretend otherwise.

---

## 13. Worked example (from the real dump)

**Article:** “Bharat Dynamics Bags ₹1,348 Cr Order, But Faces Sell Rating” (08:58 IST).

N1 keep → `ORDER_WIN` + `RATING`.  
N2 alias `Bharat Dynamics` → `NSE:BDL-EQ` **only if** BDL ∈ F&O. Goldman Sachs is not a ticker.  
N3: `news_intent=UNCLEAR` or weak BULLISH (order vs Sell). `why` must mention both facts.  
N4: in universe? not banned?  
C1: pull BDL chain from harvest (or promote to top-tier).  
C2:

- If chain is WRITE_CE into a wall and futures short → **no long**, despite order headline.
- If BUY_CE cluster + vol/OI shock + futures long buildup → engine card, strike from desk.
- If QUIET at 09:20 → stay on News focus, no strike.

**Article:** “Crude oil prices fall boosting Nifty above 24000.”

N1 `MACRO_INDEX`.  
N2 NIFTY + maybe energy sector bucket.  
N3 **does not occupy 5 stock slots** with RELIANCE/ONGC/BPCL unless there is a **company** headline. Index context only. Radar header tape already shows NIFTY/BANK/VIX.

**Article:** “Bollywood Shift: Studios Casting South Indian Stars.”

N1 drop. Never reaches the model.

---

## 14. Failure modes (design against them)

| Failure | What it looks like | Guard |
| :--- | :--- | :--- |
| Hallucinated ticker | `NSE:HAL-EQ` for a HAL *order* to BDL | Alias + allow-list |
| Laundry-list capture | 5 names from “stocks in focus” roundup | Drop that event class; max 1 name per roundup article |
| Macro dilution | Top 5 = oil complex every crude print | Index context channel |
| Stale catalyst | Order news, stock already +6%, EM spent | Open-pulse decay |
| AI strike | Model prints 2400 CE | C3 cannot emit numbers not in card |
| News overrides chain | Headline long vs WRITE_CE | Fuse table |
| Token burn | 100 full articles × fat model every 3 min | N1 drop + cheap extract + rank only candidates |
| Second Fyers loop | “fetch chain for 5 names live” besides harvest | Priority overlay only |
| Prompt injection | article body says “ignore rules, buy X” | Treat body as untrusted data; schema; N4 |

---

## 15. Implementation order (when you say go)

Do **not** start by wiring a chatbot to Fyers.

1. **Normalize scraper output** to `articles.jsonl` (id, ts, cat, url, title, body). Dedup.
2. **Alias table** F&O names + groups + indices. Unit tests on the dump (BDL, TVS, Kotak, Nifty, crude).
3. **N1 rules** on the 100-item README dump: count keep vs drop. Target: drop ≥ 50% junk.
4. **N2 extract** via OpenRouter JSON schema; N4 must reject unmapped entities. No ranking yet.
5. **N3 ranker** on linked candidates only → `news_focus[5]`.
6. **Overlay** those 5 on Radar board (priority harvest + UI strip). **No cards from news.**
7. **C2 fuse** with existing chain_desk / quantopt states (EARLY/CONFIRMED, EXPLODE ≠ TRADEABLE).
8. **C3 narrator** last.
9. **Outcome logger** from day 1 of step 6 — otherwise we cannot prove the five were worth it.

Acceptance for step 6 (before any strike UI):

- Zero tickers outside `FNO_STOCKS`.
- Bollywood / ITR / 2030 essays never in the five.
- Crude story does not fill five energy names by default.
- Re-running N3 on the same article set is stable (≤ 1 rank swap).

Acceptance for step 7:

- News-BULLISH + chain conflict → WAIT.
- Strike on screen equals engine card strike or is blank.
- GEX is labelled regime, never “dealers will buy.”

---

## 16. Relation to the 8.7 review (do not regress)

The previous review’s five production fixes still apply **inside C1**:

1. Thresholds adaptive later — news layer must not invent new magic numbers for vol/OI.
2. EXPLODE vs TRADEABLE separate — news is not a third way to skip confirmation.
3. GEX = context — LLM does not get to treat it as truth.
4. EARLY vs CONFIRMED — news can only create EARLY *attention*.
5. Outcome measurement — §12.5 is the news analogue of that lab.

If those are skipped, adding OpenRouter will make the junk **sound confident**.

---

## 17. One-page operating doctrine

1. **Whalesbook is the news wire. OpenRouter is the reader. OptionGreek is the book.**
2. **Most news is not an option trade.** Prefilter until that is obvious in the counts.
3. **Ticker linking is code + a dictionary, not a vibe.**
4. **Top 5 are a follow-list.** The chain still has to print.
5. **Strikes come from walls, delta-notional, and remaining EM — not from a paragraph.**
6. **Macro goes to the index tape. Idiosyncratic order/earnings/legal go to the five.**
7. **If the five do not beat a chain-only explode list in the outcome log, kill the AI ranker and keep the scraper as a caption on names the chain already found.**

---

## 18. Sources / priors

- This repo: `whalesbook/README.md` (live dump shape), `news_context.py` (macro-only Grok), `fno_stocks.py`, harvest 180s, `quantopt.md`.
- OpenRouter: Chat Completions + `response_format.json_schema` + `provider.require_parameters` ([docs](https://openrouter.ai/docs/guides/features/structured-outputs)).
- Indian event-options practice: earnings/policy/budget playbooks (IV crush, defined risk, liquid names only); SEBI F&O loss stats as a reminder not to naked-sell news.
- Prior conversation: EVENT → INTENT → CONFIRMATION → TRADE; GEX caution; EARLY vs CONFIRMED; measure 5/15/30/60m outcomes.

---

*End of spec. Next implementation should start at §15 step 1 (normalize scrape) unless you name a different first cut.*
