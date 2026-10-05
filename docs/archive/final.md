# FINAL.md — AI + Chain Analysis (build this)

**Date:** 29 August 2026  
**Status:** Implementation bible for the button. **No code in this pass.**  
**Parents:** `ai-system.md` (doctrine), `quantopt.md` (chain events), `PROJECT_REPORT.md` (one harvest writer).

This file is the **only** spec to implement next. Ignore JustTicks. Ignore whalesbook `server.py` (that is the JustTicks hub). News source is **whalesbook.com market-news only**.

---

## 0. What the user clicks

Radar header, next to **Scan**:

```
[ Scan ]   [ AI + Chain ]
```

One click runs **one job**. No second Fyers universe scan. No JustTicks.

```
click
  → scrape whalesbook.com/market-news (today IST)
  → send compact articles + F&O allow-list to Nemotron
  → parse top 5 stocks + 1-line news each
  → code-validate vs FNO universe
  → mark HOT
  → analyse those 5 on our chain desk
  → paint News-focus strip + hot flags
```

**News never buys. Chain never invents a ticker. Model never invents a strike.**

---

## 1. Locked model + endpoint

| Item | Value |
| :--- | :--- |
| Playground | https://openrouter.ai/nvidia/nemotron-3-ultra-550b-a55b:free |
| Model slug | `nvidia/nemotron-3-ultra-550b-a55b:free` |
| HTTP | `POST https://openrouter.ai/api/v1/chat/completions` |
| Auth | `Authorization: Bearer $OPENROUTER_API_KEY` |
| Price | $0 in / $0 out (**free variant**) |
| Context | 1M tokens (we will send ~8–20k, not the million) |
| Max completion | 65,536 (we cap ~800) |
| Tools | yes (`tools`, `tool_choice`) |
| `response_format` / JSON schema | **NO** — this free endpoint does **not** enforce JSON |
| Reasoning | default **on**, default effort **high** — turn **off** or `low` for this job |
| Typical latency | 3–25s TTFT; NVIDIA provider ~8 tok/s |
| Availability | ~75% over 3d — **must retry** |
| Free rate limit | **20 req/min**. Daily: **50/day** if account never bought ≥$10 credits, else **1000/day** |
| NVIDIA logging | free endpoint **logs prompts**. Never send Fyers tokens, account ids, or full chains. |

```http
POST /api/v1/chat/completions
Host: openrouter.ai
Authorization: Bearer sk-or-v1-...
Content-Type: application/json
HTTP-Referer: https://optiongreek.local
X-Title: OptionGreek AI+Chain
```

```json
{
  "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
  "temperature": 0.1,
  "max_tokens": 800,
  "reasoning": { "enabled": false },
  "messages": [ { "role": "system", "content": "..." }, { "role": "user", "content": "..." } ]
}
```

If the SDK rejects `reasoning.enabled: false`, omit it and **strip reasoning from the parsed message** (`message.content` only; ignore `reasoning` / `reasoning_details`).

**One click = one LLM call.** Stay inside 20 RPM. Do not extract-per-article (that would burn the 50/day cap).

Env:

```
OPENROUTER_API_KEY=
OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

Do not reuse `GROK_API_KEY` for this path.

---

## 2. Click contract (backend job)

`POST /api/v1/radar/ai-chain`  
Auth: same as Radar (Fyers session not required for scrape+LLM; **required** for chain analyse).

Returns immediately:

```json
{ "success": true, "job_id": "aic-...", "status": "queued" }
```

Poll: `GET /api/v1/radar/ai-chain/jobs/{job_id}`

Job phases (UI status line):

| phase | meaning |
| :--- | :--- |
| `scraping` | fetching whalesbook list + bodies |
| `ranking` | Nemotron call |
| `validating` | FNO allow-list, alias, dedupe |
| `analysing` | chain_desk on the 5 hot names |
| `done` | payload ready |
| `failed` | error_message |

Job payload when `done`:

```json
{
  "success": true,
  "status": "done",
  "asof_ist": "2026-08-29T09:12:00+05:30",
  "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
  "articles_in": 48,
  "articles_kept": 22,
  "picks": [
    {
      "rank": 1,
      "symbol": "NSE:TVSMOTOR-EQ",
      "name": "TVSMOTOR",
      "news": "Shifting Norton Atlas production to Hosur for cost/scale.",
      "news_intent": "BULLISH",
      "event_type": "ORDER_WIN",
      "repeat_n": 1,
      "hot": true,
      "article_ids": ["6a3c9d67..."],
      "chain": { "grade": "WATCH", "explode_state": "NONE", "intent": "WRITE_PE", "setup_score": 61 }
    }
  ],
  "index_context": { "bias": "MIXED", "why": "crude down, GIFT green", "follow": ["NSE:NIFTY50-INDEX"] },
  "rejected": [{ "raw": "Knack Packaging", "reason": "not_fno" }]
}
```

Frontend: disable the button while job running; show phase; on done, render **News focus** strip of 5; mark those symbols HOT in bull/bear/middle lists.

---

## 3. Scrape (whalesbook only — no JustTicks)

**Source:** `https://www.whalesbook.com/market-news/English/all`  
**Optional date filter:** today + yesterday IST (the README dump already did this).

### 3.1 What to fetch

1. List page → items: `id`, `url`, `title`, `category`, `ts_ist`.
2. For the newest **N=40** items (cap), fetch body (2–6 sentences). If list already has a summary, **do not** hit 40 article pages — summaries are enough for ranking.

Timeout 12s per page. Concurrent 4. UA: normal browser. Cache articles by `id` for 2 hours so a second click in the same session is cheap.

Output row:

```
id, url, ts_ist, category, title, body, source="whalesbook"
```

Persist `backend/app/data/news_articles.jsonl` (append, dedupe on `id`).

### 3.2 Hard prefilter (code, before the model)

**Drop**

- IPO of unlisted names
- ITR / process explainers
- “2030 outlook” / wealth-mgmt essays
- Entertainment / Bollywood unless a listed F&O media name is explicit
- Ex-dividend laundry lists of 10+ names
- Duplicate URL / same title within 6h

**Keep**

- Order wins, earnings, ratings, M&A, legal, named-company guidance
- Macro/commodity/RBI → keep as **index context**, not as stock slots

If keep-count < 8, still run the model; **do not force 5 stocks**.

**JustTicks is out.** Do not import `justticks_oi_cmd_scraper.py`. Do not call `/api/run-justticks`.

---

## 4. Strict prompt (the whole point of the model)

Nemotron on this endpoint **cannot** lock JSON schema. So the prompt + a **tool** (preferred) + a **parser** must do the job.

### 4.1 Preferred: one tool call

Define a function `submit_top5` and set `tool_choice` to that function. The model must fill:

```
picks: array length 0–5
  rank: 1–5
  name: short NSE name (TCS, TVSMOTOR, SBIN) — NOT a sentence
  news: ≤ 18 words, fact from the articles, no advice
  intent: BULLISH | BEARISH | VOL | UNCLEAR
  event_type: ORDER_WIN | EARNINGS | RATING | M_AND_A | LEGAL | GUIDANCE | MACRO_INDEX | OTHER
  article_ids: subset of provided ids
index_bias: RISK_ON | RISK_OFF | MIXED
index_why: ≤ 12 words
```

If tools fail on the free route, fall back to **JSON-only text** and parse.

### 4.2 System prompt (verbatim to implement)

```
You are a filter for Indian NSE F&O intraday options.
You do NOT pick trades. You do NOT pick strikes. You do NOT invent tickers.

You will receive:
- TODAY_IST
- FNO_NAMES: allowed short names only
- ARTICLES: id, time, category, title, body

Task: choose up to 5 DISTINCT F&O names that can reasonably MOVE TODAY
because of these articles.

Rules:
1. name MUST be copied from FNO_NAMES. If the company is not in FNO_NAMES, skip it.
2. Prefer company-specific catalysts (order, earnings, legal, M&A, rating+number).
3. If the same name appears in 2+ articles, it is stronger — still only one slot.
4. Macro (crude, RBI, GIFT, Nifty) goes to index_bias, NOT to five random oil/bank names.
5. Drop essays, IPOs of unlisted firms, tax explainers, entertainment, 2030 outlooks.
6. news must be ≤ 18 words, a fact from the article, no "buy/sell/target".
7. intent is a headline hint, not a trade. Mixed order+Sell rating = UNCLEAR.
8. Return AT MOST 5. Returning 2 good names is better than padding.
9. Call submit_top5. No extra prose.
```

### 4.3 User payload shape (compact)

Do **not** send 100 full pages. Send kept articles as:

```
#12 08:58 Aerospace
ID 6a3ca074
TITLE Bharat Dynamics Bags ₹1,348 Cr Order, Faces Sell Rating
BODY Bharat Dynamics HAL contract ₹1347.71 cr … Goldman Sachs Sell …
```

Plus:

```
FNO_NAMES: RELIANCE, TCS, HDFCBANK, ... (comma list of short names from FNO_STOCKS)
TODAY_IST: 2026-08-29 09:10
```

Short names = `symbol.split(":")[-1].replace("-EQ","").replace("-INDEX","")`.

Cap user message ~12k chars. If over, keep newest kept articles first.

---

## 5. Validate in code (model is not trusted)

After the tool/JSON:

```
allow = { short_name → NSE:SYMBOL-EQ } from FNO_STOCKS + indices
for each pick:
  name = uppercase, strip spaces
  if name not in allow: reject (log raw)
  symbol = allow[name]
  article_ids must ⊆ scraped ids
  news = first 18 words, strip "buy/sell/accumulate"
  rank unique 1..n
dedupe symbol (keep highest rank / more article_ids)
max 5
MACRO_INDEX-only picks → move to index_context, remove from picks
```

**Repetitive stocks (your “repetive” rule):**

```
repeat_n = count of kept articles that mention this name (alias hit)
hot = True for every validated pick
hot_boost if repeat_n >= 2  → sort those first among the 5
```

Also mark HOT if the harvest already has `EARLY`/`CONFIRMED` explode on that symbol.

Rejected names (not F&O) go to `rejected[]` for the UI (tiny, optional).

If 0 picks survive, job is still `done` with empty picks — **not** a fake 5.

---

## 6. Analyse those 5 on OUR chain (hot symbols)

This is OptionGreek, not the LLM.

### 6.1 Mark hot

On the live board / symbol_store:

```
hot_symbols = set(picks.symbol)
row.hot = symbol in hot_symbols
row.news_rank, row.news_blurb, row.news_intent, row.repeat_n
```

Harvest priority (`build_harvest_priority`): **`_add(hot_symbols)` first**, before locked ideas / TOP_FNO. So the next harvest walk hits them immediately.

### 6.2 Chain pass (same job, after validate)

For each of the 5, in order:

1. Read store chain (`symbol_store.get_chain`). If fresh (< stale_soft) → `chain_desk.evaluate` on store.
2. If missing/stale **and** Fyers authed → **one** optionchain fetch through the **existing rate limiter** (not a new 187-name scan).
3. Stamp `explode_state`: `NONE | EARLY | CONFIRMED` using `quantopt` rules (first print = EARLY; persist vs last digest = CONFIRMED).
4. Attach `grade`, `chain_bias`, `top_anomaly`, `setup_score`, `flags` to the pick.

If Fyers is not authed: still return the 5 news picks with `chain: null` and UI “login to analyse”.

### 6.3 Fuse (no EVENT → BUY)

| news_intent | chain | futures | UI action |
| :--- | :--- | :--- | :--- |
| any | missing | — | NEWS only |
| BULLISH | BUY_CE + futures long | agree | show engine card |
| BULLISH | WRITE_CE / PIN / CONFLICT | — | WAIT, keep HOT |
| BULLISH | BUY_CE + futures short | fight | WAIT |
| VOL | both wings / straddle shock | — | no direction |
| UNCLEAR | EXPLODE EARLY | — | follow, no TRADEABLE |

Strike on screen = engine card strike **or blank**. Never Nemotron’s number.

---

## 7. UI (Radar)

### Header

```
[Tradeable] [Scan] [AI + Chain] [Login]
```

Button states: idle / Scraping / Ranking / Analysing / done (pulse off).

### News focus strip

Place **under the header tape**, above the 3 columns. Five compact chips:

```
1  TVSMOTOR  HOT
   Norton production to Hosur
   CHAIN WATCH · WRITE PE
```

Click chip → `setSelected(symbol)` (existing bottom chain).

If analysing, chips show news first, chain fields fill in when that symbol finishes (job payload can stream via poll every 1.5s).

### Lists

In bull/bear/middle rows, if `row.hot`:

```
TCS   HOT · NEWS
```

Do **not** auto-apply OI/VOL/SUP/RES filters. Hot is a **follow mark**, not a fourth filter that fires on everyone.

### Empty / fail

- Scrape fail → “Whalesbook unreachable”
- 429 OpenRouter → “AI limit, retry in a minute”
- 0 F&O picks → “No F&O catalysts in this batch”
- Partial chain → news chips still show

---

## 8. Frontend API

`frontend/lib/api.ts`:

```
radar.startAiChain() → POST /radar/ai-chain
radar.getAiChainJob(id) → GET /radar/ai-chain/jobs/{id}
```

`OptionFlowRadar.tsx`:

- state: `aiJob`, `aiPicks`, `hotSet`
- poll like `runScan`
- `hotSet` used in `SetupTable` + middle list
- persist last `aiPicks` in component state until next click (do not wipe on harvest poll)

---

## 9. Files to add / touch (when implementing)

**Add**

| File | Role |
| :--- | :--- |
| `backend/app/services/news_scraper.py` | whalesbook list+body, cache, jsonl |
| `backend/app/services/news_aliases.py` | short name ↔ `NSE:…-EQ` |
| `backend/app/services/ai_ranker.py` | OpenRouter Nemotron call, parse tool/JSON |
| `backend/app/services/ai_chain_job.py` | orchestrate scrape → rank → validate → analyse |
| `backend/app/routes/ai_chain.py` | POST/GET job |
| `backend/app/data/news_articles.jsonl` | scrape archive |
| `backend/app/data/ai_chain_outcomes.jsonl` | later measurement |

**Touch**

| File | Change |
| :--- | :--- |
| `backend/app/core/config.py` | `openrouter_api_key`, `openrouter_model`, `openrouter_base_url` |
| `backend/.env.example` | same |
| `backend/app/main.py` | include router |
| `backend/app/services/option_flow_radar.py` | `build_harvest_priority`: hot first |
| `backend/app/services/symbol_store.py` / board slim | keep `hot`, `news_*` on rows if we stamp them |
| `frontend/lib/api.ts` | two methods |
| `frontend/components/OptionFlowRadar.tsx` | button, strip, HOT chip |

**Do not touch**

- `whalesbook/server.py` JustTicks
- extra strategy pages
- `news_context.py` Grok macro (leave; this path is separate)

---

## 10. Alias table (minimum to ship)

Build from `FNO_STOCKS` automatically (`TCS` → `NSE:TCS-EQ`) **plus** common English names:

```
bharat dynamics → BDL          (only if BDL in FNO)
tvs motor       → TVSMOTOR
kotak           → KOTAKBANK
hdfc bank       → HDFCBANK
tcs / tata consultancy → TCS
infosys         → INFY
reliance        → RELIANCE
sbi             → SBIN
nifty / nifty 50 → NIFTY50-INDEX
bank nifty      → NIFTYBANK-INDEX
india vix       → INDIAVIX-INDEX
```

Group words (`tata group`, `adani`) **do not** auto-enter the five. They can appear in `rejected` or index/sector notes.

Unit test the 25 Jun dump:

- Bollywood → not a pick
- ITR refund → not a pick
- Crude / Nifty 24000 → index_context, not 5 oil names
- TVS Norton → TVSMOTOR if in FNO
- BDL order → BDL if in FNO else rejected `not_fno`
- Fairfax / IDBI → only if IDBI/CSB in FNO

---

## 11. Logics recap (do not regress)

From `quantopt.md` + review:

1. Tags on the **chain** stay rare/exclusive. This job does not stamp OI/VOL/SUP/RES on the five.
2. EXPLODE ≠ TRADEABLE. News-BULLISH is not a long.
3. GEX = regime word on the card, not “dealers will buy.”
4. First chain print on a news name = EARLY. Second harvest persistence = CONFIRMED.
5. Log for later: at click time, store picks + chain snapshot; at 15m/60m append underlying return. **Do this as jsonl from day 1** so we can see if the five were worth it.

**Repeat logic (this job’s extra):**

```
repeat_n >= 2  →  sort earlier in the five, still one slot
repeat across clicks in the same session → keep HOT until EOD or user Clear
```

---

## 12. Failure / limits handling

| Error | UX |
| :--- | :--- |
| Whalesbook HTTP fail | fail job, keep last picks if any |
| OpenRouter 429 | fail with retry-after; button cooldown 60s |
| OpenRouter 503 / empty providers | one retry after 3s, then fail |
| Tool parse fail | regex-extract JSON object from content; if still fail, fail job |
| Model returns 5 non-FNO names | all rejected, 0 picks, not a crash |
| Fyers 429 mid-analyse | return news picks + partial chain, mark rest `chain_error: rate_limit` |
| Job > 90s | mark failed timeout |

Free daily cap 50: **one click ≈ 1 LLM call**. Scrape is unlimited locally. Do not auto-fire this on harvest tick.

NVIDIA logs the prompt: send **titles/summaries only**, no user identity, no tokens.

---

## 13. Implementation order (do in this sequence)

1. Config + OpenRouter ping (`max_tokens=16`, “ok”).
2. `news_scraper.py` against live whalesbook list; save jsonl; **no LLM**.
3. Prefilter + alias tests on the committed README dump.
4. `ai_ranker.py` with the verbatim prompt + tool; parse; N4 validate. Fixture: dump articles → 0 entertainment names.
5. Job orchestrator without chain (picks only) + API + button that shows 5 blurbs.
6. Chain analyse on the 5 via store/limiter; HOT on board; harvest priority.
7. Fuse WAIT vs card; bottom panel already works via `selected`.
8. Outcomes jsonl.

**Done when**

- Click scrapes whalesbook, not JustTicks.
- Five names are FNO or fewer.
- Each has a short news line from the article.
- Those symbols are HOT and chain-analysed.
- No strike appears unless `chain_desk` made a card.
- Second click does not stamp the rest of the book with news tags.

---

## 14. Exact curl (sanity)

```bash
curl https://openrouter.ai/api/v1/chat/completions \
  -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -H "HTTP-Referer: https://optiongreek.local" \
  -H "X-Title: OptionGreek AI+Chain" \
  -d '{
    "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "temperature": 0.1,
    "max_tokens": 16,
    "reasoning": {"enabled": false},
    "messages": [{"role": "user", "content": "Reply with the single word pong"}]
  }'
```

If this fails, do not build the button yet — key or free-quota first.

---

*Implement from §13. This file overrides `ai-system.md` on model/endpoint, one-shot ranking, and the button job. Doctrine from `ai-system.md` and `quantopt.md` still applies.*
