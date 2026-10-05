# QUANTOPT — Option-chain research, exploding-option capture, and the logic we should implement

**Date:** 29 August 2026  
**Status:** Research + implementation spec only. **No code in this pass.**  
**Purpose:** Diagnose why the Radar tags every name `OI · VOL · SUP · RES`, then dump how real desks, scanners, and Indian F&O writers actually catch *exploding* options — and the exact logics to implement next.

This file is the thinking document. Do not treat `PROJECT_REPORT.md` as superseded; that file is the product teardown. This file is the **quant brain** for the next engine.

---

## 0. What the screenshot proves (the real problem)

`image.png` is the live desk. Read it as evidence, not as UI taste.

| Observation | What it means |
| :--- | :--- |
| Filter **Resistance** is on. Count = **132**. | A third of the F&O book is “at resistance.” That is not a level. That is a default. |
| Almost every row shows `OI VOL SUP RES` | Tags are not *events*. They are *always-on attributes*. |
| Bull list and Resistance list share TCS, TATAPOWER, IDEA, BAJFINANCE | The middle pane is not a different question. It is the same book with a sticker. |
| TCS: PCR 0.79, put wall 2,300, call wall 2,400, γ-wall 2,300, max pain 2,320, IV skew 0, futures UNKNOWN, BUY CE 2,340 | The card is guessing a long while futures are missing and skew is dead. |
| TCS chain: CE volume mostly 0–675, PE volume 1.6L–13.9L, PE ΔOI −26k to +97k | The live book is **put-heavy flow**, not a clean call-buy. The tag set still prints all four labels. |
| IDEA: ΔOI 10.98L, vol 2,825L | A real volume monster sits next to names with 27L vol, same badges. |
| MPHASIS: ΔOI 84,150, vol 27L, tags `OI · VOL · SUP` | Slightly cleaner, still not exclusive. |
| ASHOKLEY: ΔOI 39.15L, vol 534L, still `OI VOL SUP RES` | Size does not earn a unique tag. |

**One-line diagnosis:** we are labelling *presence of a chain* (every F&O name has OI, volume, a put wall, a call wall). We are not labelling *an anomaly relative to that name’s own book, the harvest distribution, and a directional intent*.

If every name gets every tag, **no filter can catch a move**. Filters need *rare, exclusive, quantified events*.

This is not a CSS problem. It is a **classification problem**.

---

## 1. Law of tags (quant, not coding)

A tag is allowed only if all four hold:

1. **It is false for most of the universe today.** Target: each tag on ≤ 10–15% of harvested names. If Resistance is 132/187, the tag is broken.
2. **It answers one question.** `SUP` cannot mean “has a put wall.” Every chain has a put wall (argmax PE OI below spot).
3. **It is not implied by another tag.** A `WALL_SUPPORT` print that already required high ΔOI + high volume must not auto-stamp `OI` and `VOL`. Otherwise AND-filters collapse to the same list.
4. **It is ranked, not boolean-first.** The desk wants “the 8 names whose call-writing at the wall is in the top decile of ΔOI *and* premium is falling,” not “all names near a wall.”

**Hard rule for the UI:** a name gets **one primary intent** and at most **one location** and at most **one size** tag.

```
PRIMARY (exactly one)
  WRITE_CE | WRITE_PE | BUY_CE | BUY_PE | UNWIND_CE | UNWIND_PE | PIN | VOL_EXPLODE | QUIET

LOCATION (0 or 1, only if exceptional)
  AT_PUT_WALL | AT_CALL_WALL | THROUGH_CALL | THROUGH_PUT | ATM_CLUSTER

SIZE (0 or 1, only if exceptional vs peers)
  OI_SPURT | VOL_SHOCK | BOTH_SHOCK
```

Seeing `OI VOL SUP RES` on one row must become **impossible**.

---

## 2. Research map (what was read)

Research was pulled from US flow desks, GEX shops, Indian F&O writers, scanners, academic lead–lag work, and X accounts. The point is not to copy a SaaS. The point is to steal **which questions they ask**, because those questions already separate signal from junk.

### 2.1 US unusual-options / flow desks

| Source | What they actually filter | Why it matters for us |
| :--- | :--- | :--- |
| Market Rebellion / Najarian Heat Seeker | Unusual = large **notional**, **at the offer**, **volume > OI**, **OTM**, low natural probability vs IV | “Unusual” is a **conjunction**, not a high-volume list. |
| Unusual Whales | Size>OI, Vol>OI, ask-side, opening bias, multi-leg exclusion, premium floors ($25k–$500k), %OTM, DTE bands | One print is the start. Contract history, IV, fill vs bid/ask, net premium, and tape reaction decide if it is real. |
| Cheddar Flow | Sweeps vs blocks, opening, above-ask, unusual volume vs **that contract’s** history | Sort then **compare**. Volume without OI context is noise. |
| FlowAlgo / TradeAlgo / Alpha Suite / CrossVol | Sweep = urgency; block = negotiated size. ~90% of tape is MM. Keep sweeps > ~$250k–$500k premium, vol/OI > 2, opening. | Urgency ≠ size. We cannot see ISO sweeps on NSE the same way, so we must **simulate intent** with premium direction + ΔOI + vol/OI. |
| iPresage / StrikeWatch | Next-day OI confirmation: vol spike + OI up = new position; vol spike + OI flat/down = close/roll. MM hedge exclusion. | **Volume without OI persistence is not a position.** |
| FlashAlpha coalescing | Same contract + same side within 500ms = one sweep | NSE has no OPRA tape. Do not fake “sweeps.” Use **strike concentration in one harvest window** instead. |
| Barchart / CBOE-style UOA | Vol/OI > 3, min volume, min OI, moneyness, DTE | Cheap first cut. Still needs premium direction and next snapshot OI. |
| Optionomics / Signal Pilot | Pattern badges (Aggressive Call, Volume Spike, Whale) + score 0–100. GEX first, flow second. | **Regime then trigger.** Flow in +GEX ≠ flow in −GEX. |

Consensus from flow people (including `@AnthonySandford` / `@unusual_whales` on X):

> A big order is only the start. Read IV, bid/ask, vol vs OI, net premium, strike location, expiry, contract history, and whether the **stock tape** agrees.

### 2.2 Dealer-positioning / GEX desks

| Source | Core object | Desk use |
| :--- | :--- | :--- |
| SpotGamma | GEX, Call Wall, Put Wall, Volatility Trigger / flip, HIRO (flow → dealer delta) | Regime: +GEX mean-reverts, −GEX trends. Walls are **hedging concentrations**, not chart S/R. |
| Unusual Whales Spot Gamma heatmap | Per-strike dealer long/short gamma | Green = pin/chop. Flip = character change. |
| QuantWheel / GEXMetrix / ExpireWorthless | GEX formula, wall definitions | Formula first (see §5). Sign convention must be explicit. |
| VannaCharm / GammaSonar / GEXRadar | VEX (vanna), CEX (charm), DEX | Gamma is not enough. IV change and time move delta **with spot flat**. |
| TradeEcho | GEX = reservoir (stock of positions). Flow = river (today’s prints). | Do not mix. Structure answers “what kind of market.” Flow answers “who is acting now.” |

**Call wall / put wall — the version that is not junk:**

- Call wall = strike with **largest call gamma (or call GEX)**, typically above spot. Dealers who are short those calls **sell the underlying into rallies toward it** → resistance *while the wall is live*.
- Put wall = strike with **largest put gamma**, typically below spot. Dealer hedge near it is **support only under the short-put / long-gamma assumption**. Some models invert this. **Never tag SUP just because argmax PE OI exists.**
- Break of a wall **flips** the hedge: through the call wall can become a squeeze (dealers buy). Through the put wall can become a cascade.

SpotGamma’s own later copy is careful: walls are **scenario references**, not guaranteed floors. Public OI cannot prove the dealer side.

### 2.3 Indian F&O chain practice (this is our market)

NSE is **not** OPRA. There is no public bid/ask aggressor flag, no ISO sweep tape, no opening/closing code on every print. Indian desks therefore invented a different language that is **more honest for Fyers data**.

| Source | What they treat as the signal |
| :--- | :--- |
| NiftyTrader / ArthaLearn / Stoxra / TradingZenith / Stolo | **OI is written by sellers.** Highest CE OI = resistance (writers sold that ceiling). Highest PE OI = support (writers sold that floor). |
| Sensibull | OI vs time, multi-expiry, custom windows. Chain is a **map of writer levels**, not a buy list. |
| Opstra (Definedge) | Unusual Options Activity = volume vs OI **per contract** across ~17–20k contracts. Historical OI, IV percentile, GEX. |
| Quantsapp | OI pulse, option pain, option triggers, buildup scanner, unusual activity by **price / OI / volume / IV separately**. |
| MarketNetra | **OI spurt** = 3–5× normal add rate, **concentrated** on 1–3 strikes, in a 30-min window. Premium falling + OI up = writing. Premium rising + OI up = buying. |
| NiftyDesk | PCR must be split by expiry. **OI migration** (max CE OI walking down) is the tell. |
| NSE participant OI (FII/DII/Pro/Client) | Institutional futures + options split. Retail-heavy client OI is often the wrong side. |

**The Indian four-quadrant (must keep, but apply to the *option premium* and to *futures*, separately):**

| Premium or futures price | OI | Name | Intent |
| :--- | :--- | :--- | :--- |
| ↑ | ↑ | Long buildup | Fresh buying |
| ↓ | ↑ | Short buildup | Fresh writing |
| ↑ | ↓ | Short covering | Squeeze / exit of shorts |
| ↓ | ↓ | Long unwinding | Exit of longs |

**Critical Indian correction:** a beginner sees 80 lakh CE OI and thinks “bulls bought calls.” The professional reads **writers sold that strike** — they do **not** want spot through it.

So `SUP` / `RES` on NSE are **writer walls**, and they are only live if:

- OI at that strike is **concentrated** vs the rest of the chain (not a flat 80k on every strike),
- **ΔOI today is adding** (wall being built) or at least not unwinding,
- premium move agrees (writing = premium down + OI up),
- spot is **actually near** that strike (distance in steps or %).

A dead wall (huge old OI, today’s ΔOI flat, premium idle) is not a tag.

### 2.4 Exploding options / gamma squeeze research

| Source | Recipe |
| :--- | :--- |
| SpotGamma squeeze scanner | Near-dated (0–7 DTE) OTM calls 5–15% OTM, call volume > 3× 20d avg, **concentrated in 2–3 strikes**, IV rising, term structure inverting, price approaching call wall, often high short interest. |
| Belanger | Contract vs **its own** history: 3–10× own ADV, vol > 2× OI, IV rising while bought, ≥50–80% at offer. |
| Tradewink | 5× strike ADV + short interest > 15–20% + low float. |
| WalletInvestor / breakout checklist | Price ↑ + volume ↑ + OI ↑ = new money. Price ↑ + volume ↑ + OI ↓ = covering (often fails). Low IV percentile then expansion. Call-wing IV rising (reverse skew) = squeeze risk. |
| OptionVisualizer | IV spike = IV > 3× **own 30d average**, not “IV is 40%.” |

**Exploding option ≠ busy chain.** A name with 400L of option volume every day is not exploding. A name whose **hottest strike** is 5× its own median and 3× its own OI, with IV up, is exploding.

### 2.5 Greeks that actually move the underlying

| Greek | Formula intuition | Why a stock desk cares |
| :--- | :--- | :--- |
| **Delta** | ∂V/∂S | Hedge ratio. Sum(Δ × OI × lot × 100-or-lot) = **DEX** = shares dealers theoretically hold. |
| **Gamma** | ∂Δ/∂S | How fast the hedge must change. Sum → **GEX**. +GEX dampens, −GEX amplifies. |
| **Vega** | ∂V/∂σ | IV shock P&L. Not a direction tag by itself. |
| **Theta** | ∂V/∂t | Expiry gravity. High θ + pin = do not fade the magnet blindly, but also do not treat max pain as a target all week. |
| **Vanna** | ∂Δ/∂σ = ∂vega/∂S | **IV drop forces delta change with spot flat.** Classic “vol-reset rally”: IV ↓ → dealers buy (in the usual short-put book). |
| **Charm** | ∂Δ/∂t | Time alone unwinds hedges. Afternoon drift into expiry, 0DTE last two hours. |

Fyers chain API can return delta, gamma, theta, vega, IV per leg (`greeks=1`). **Vanna and charm are not in the feed.** They must be derived from BS on the IV surface, or skipped until we store IV snapshots.

**GEX (common public formula):**

```text
GEX_contract = Γ × OI × multiplier × S² × 0.01 × sign
sign: calls +1, puts −1   (dealer-short-to-customers assumption)
Net GEX     = Σ GEX_contract
Call wall   = strike with max call GEX (or max call gamma×OI) above/near spot
Put wall    = strike with max |put GEX| below/near spot
Flip / zero = price where cumulative GEX changes sign
```

DEX (first order, “where dealers are now”):

```text
DEX_contract = Δ × OI × multiplier × S
```

SpotGamma: GEX = dollars of delta change per **1%** spot move. Other shops use per **1 point**. Pick one unit and never mix.

**Which greeks matter for *exploding* names (priority):**

1. **Gamma at the hot strike** (is this a hedge-amplifying strike or a pin?)
2. **Delta notional of today’s volume** (how many shares of pressure did today create?) — `volume × |Δ| × lot`
3. **IV / vega of the hot strike** (are they paying for vol or just rolling?)
4. **Net GEX regime of the name** (will a push through the wall extend or fade?)
5. Vanna/charm only after we have an IV history.

Theta is a **warning** (do not buy 0.2-delta 1-DTE as a swing), not a selector.

### 2.6 Stock ↔ option relationship (lead / lag)

Academic + microstructure:

- Patel, Putniņš et al.: options contribute **~25%** of price discovery; more around news; insiders prefer options for leverage.
- Index studies (1-min): futures and options often **lead cash**. Options can lead futures on many days.
- Near-the-money option activity forecasts stock direction **only in liquid names**. Illiquid chains do not lead.
- Delta-hedging footprint is **50–100 ms** on US equities. We will never see that on a 3-minute Fyers harvest. We see the **residue**: futures OI, spot vs VWAP, and whether the underlying printed in the direction of the option intent *after* the OI/vol shock.

**Practical NSE translation:**

```
Options can lead stock when:
  - the name is liquid (index or heavy F&O)
  - the shock is concentrated (1–3 strikes)
  - vol/OI is high (new position)
  - premium direction is buy (not write)
  - futures OI agrees (long buildup with call buy, short buildup with put buy)
  - spot has not already completed the expected move (straddle unused)

Options lag / are hedges when:
  - put buy while futures are long (collar / protection)
  - both wings up in volume (straddle, event)
  - multi-strike equal size (spread)
  - IV crush after a known event
```

**Never recommend BUY CE because PCR < 1.** PCR is sentiment + writer inventory, not a trigger.

### 2.7 IV surface: skew, term, expected move

| Object | Formula / read | Use |
| :--- | :--- | :--- |
| ATM IV | From ATM straddle or quoted IV | Level of fear. Meaningless without history. |
| IV rank / percentile | Where today’s ATM IV sits in 1y or 6m range | High IVR → sell vol / defined-risk. Low IVR → buy vol if a catalyst exists. |
| Expected move | ATM straddle / spot  (≈ 0.85 × 1σ for weeklies) | If spot already travelled 80% of EM, **do not chase** the remaining option. |
| 25Δ risk reversal | IV(25Δ put) − IV(25Δ call)  *(state the sign)* | Put-wing bid = crash demand. **Call-wing bid (RR inverted)** = squeeze / takeover / FOMO. |
| Term structure | Front IV vs back IV | Backwardation = event or panic. Contango = calm. Front inversion + OTM call volume = explosion candidate. |

Screenshot IV skew = 0 on TCS is a red flag that the engine is not computing RR at all, or is rounding it away. A living chain almost never has perfectly flat skew.

### 2.8 X / public desks worth tracking (not to scrape — to steal questions)

| Account / shop | Useful question they repeat |
| :--- | :--- |
| @unusual_whales + Anthony Sandford | Is it opening? Did IV pay up? Did the tape confirm? |
| SpotGamma / @spotgamma | What is the gamma *regime* before the level? |
| @GammaFlowSPY | Unresolved regime + crushed IV = do not force a side. |
| Indian: Sensibull, Opstra, Quantsapp blogs | Is this writing or buying? Is the wall migrating? |
| GEX/flow clones on X | Mostly marketing. Keep the **regime + wall + flow** trio; ignore “A+ alerts.” |

---

## 3. Why our current tags are structurally junk

This section is the bridge from research to implementation. No code — only the failure modes.

### 3.1 “Support” and “Resistance” are defined as existence

Every chain has:

- a strike with max PE OI at or below spot → we call it put wall → `support=true`
- a strike with max CE OI at or above spot → call wall → `resistance=true`

If we also OR in “spot within 1.5–2.5% of the wall,” **ATM names fire both**. That is why Resistance=132 and every row shows SUP and RES.

**Correct definition (Indian writer + GEX hybrid):**

`AT_PUT_WALL` only if **all** of:

1. Put-wall OI ≥ 1.6× median PE OI on the chain (concentration, not argmax of a flat book).
2. Distance(spot, put wall) ≤ 1 strike-step or ≤ 0.8% (near, not “in the zip code”).
3. Today’s PE ΔOI at that wall cluster is in the **top quartile of that chain** *or* vol at the wall is in the top quartile (the wall is **live**).
4. The opposite wall is **not** equally live (otherwise the tag is `PIN`, not SUP).

Same for `AT_CALL_WALL`.

If both walls are live and spot is between them → **one tag: PIN**. Never SUP+RES.

### 3.2 “OI” is coupled to volume anomalies

If `high_oi` is computed from anomalies that already required a volume floor, then OI ⇒ VOL. AND(OI, VOL) becomes tautology.

**Correct:** `OI_SPURT` is **session ΔOI** vs that name’s own size floor **and** vs harvest percentile, **ignoring volume**.

A writer can add 80k OI on a quiet premium. That is still a wall being built. It is not a volume explosion.

### 3.3 “VOL” is “the chain traded today”

Index and heavy names always clear 150k–800k combined volume. Absolute floors stamp VOL on the entire liquid universe.

**Correct:** VOL is a **shock**:

```
vol_shock if
    chain_vol >= p90 of today's harvest in the same liquidity bucket
    AND chain_vol >= 1.8 × this name's own median of last N harvests (or last 5 sessions)
    AND the shock is concentrated: hottest 1–3 strikes hold >= 35% of chain volume
```

A name that always trades 400L options is not tagged VOL unless today is a **right-tail day for that name**.

### 3.4 TRADEABLE is doing double duty as a tag generator

If WALL_SUPPORT (which already requires high OI+vol at the put wall) promotes the name to TRADEABLE, and TRADEABLE names are the only ones on the board, then every visible row looks like a wall+size event. The filter universe is the same as the bull/bear columns.

**Correct split:**

- **Columns (bull / bear):** directional *setups* that passed gates (writer/buyer intent + futures agreement + not PIN).
- **Middle screen:** *events* from the **full harvest including QUIET**. A QUIET name with a VOL_SHOCK at one OTM strike is exactly the “exploding option” we want. It should show in the middle and **not** in Bullish Setups until the rest of the book agrees.

### 3.5 Max pain, PCR, futures UNKNOWN

TCS card: PCR 0.79, max pain 2320, futures UNKNOWN, BUY CE 2340.

- PCR 0.79 is mildly call-heavy inventory. In India that is often **bearish** (more call writing), not a buy-CE.
- Max pain is an **expiry-day gravity**, weak all week (empirical pull ~30–40% of the time, stronger last 60 minutes). Using it as a target on a random session is amateur.
- Futures UNKNOWN means we are missing the **first institutional layer**. No trade card without futures on a stock F&O name.

### 3.6 No distinction: writing vs buying

This is the original Indian edge, and we diluted it. ΔOI up is not a direction. **Premium change + ΔOI** is the direction.

Without LTP change on the option, every OI add looks like “interest.” Half of it is writers building a ceiling.

---

## 4. What “catching exploding options” actually means

An exploding option is a **localized, new, aggressive, convex** position that can force the underlying via dealer hedges or that reveals informed demand.

### 4.1 Five ingredients (must stack; 2/5 is not enough)

| # | Ingredient | Quant test (NSE / Fyers) |
| :--- | :--- | :--- |
| 1 | **New money** | Strike volume / strike OI ≥ 2.0 (3.0 is cleaner). Next harvest: OI up, not flat. |
| 2 | **Shock vs self** | Strike volume ≥ 3× that strike’s own recent median (or chain median if no history). |
| 3 | **Concentration** | Top 1–3 strikes ≥ 35% of today’s chain volume. Spread-across-all-strikes = rebalance/hedge. |
| 4 | **Aggression** | Option LTP ↑ with volume (buy) or LTP ↓ with volume (write). IV of that strike ↑ for buys. |
| 5 | **Convex location** | 2–12% OTM, or 0.15–0.40 \|delta\|, DTE ≤ 14 for stocks / current weekly for index. Deep ITM = replacement. Far OTM junk = lottery, only keep if notional is huge. |

Then **confirm with the stock/futures layer**:

- BUY_CE explosion + futures long buildup + spot holding VWAP → **candidate long**.
- BUY_CE explosion + futures short buildup → **hedge or conflict → no card**.
- WRITE_CE at call wall + premium down + spot failing into the wall → **fade / range / short**.
- BUY_PE + WRITE_CE together → **bearish collar / breakdown**, not two opposite tags.

### 4.2 Delta-notional is the missing “size” unit

Contracts lie. 50k of 0.05-delta OTM is not 50k of 0.45-delta ATM.

```
delta_notional_shares = Σ (volume × |delta| × lot_size)
delta_notional_rupees = delta_notional_shares × spot
```

Rank explosions by **delta-notional**, not raw volume. A 10k ATM print can outweigh a 100k far-OTM print.

Gamma-notional (squeeze fuel):

```
gamma_notional = Σ (volume_or_OI × gamma × lot_size)
```

High gamma-notional sitting **just above spot in calls** is the squeeze watch. High gamma-notional **on both wings ATM** is a pin.

### 4.3 What is *not* an explosion (do not tag)

- Index names with always-on huge volume (NIFTY, BANKNIFTY) unless **z-score vs own history** is extreme.
- Equal CE and PE volume in a ±1 strike band (straddle / event). Tag `VOL_EXPLODE` with **no direction**.
- Expiry-day OI collapse (settlement, not a thesis).
- Rollover week: current-month OI down + next-month OI up = roll, not unwinding.
- Ban-list / low-liquidity names (combined volume below bucket floor).
- One harvest wonder with no second print and no futures agreement.

---

## 5. The book in layers (implementation architecture)

Keep the harvest. Change what it *means*. Four layers, each with a veto.

```
L0  UNIVERSE      liquid F&O, not banned, chain rows ≥ 8, combined vol ≥ bucket floor
L1  STRUCTURE     PCR, walls, GEX regime, flip, skew, max pain (expiry-only), ATM EM
L2  FLOW          per-strike: ΔOI, volume, vol/OI, premium Δ, IV Δ, buildup class
L3  FUTURES/SPOT  4-quadrant futures OI, basis, VWAP, HTF if we have it
L4  DECISION      one primary intent, optional location, optional size, else QUIET
```

**Vetoes (no TRADEABLE card):**

- L0 fail
- L1 PIN / negative-gamma *and* no directional flow
- L2 both wings exploding
- L3 futures missing on stocks (index can proceed with cash GEX)
- L3 futures opposite to option intent
- Expected move already spent
- Intent is UNWIND / COVERING only (watch, do not chase)

### 5.1 Structure layer (slow reservoir)

Compute once per harvest per name.

| Metric | How | Tag / use |
| :--- | :--- | :--- |
| OI PCR | PE OI / CE OI on the **traded expiry** (not all expiries mashed) | Context. Extremes vs **that name’s own 20-session PCR**, not 1.2 forever. |
| Volume PCR | PE vol / CE vol **today** | Today’s activity. Can flip while OI PCR is slow. |
| Call wall | Max (gamma×OI or CE OI) **above** spot with concentration test | Live only if ΔOI or vol at cluster is hot. |
| Put wall | Symmetric below | Same. |
| GEX profile | Γ×OI×lot×S²×0.01 with CE+, PE− | Regime: net GEX sign. |
| Flip | Spot vs zero-GEX strike | Above = dampen. Below = amplify. |
| 25Δ RR | IV_put_25Δ − IV_call_25Δ | Squeeze watch if inverted. |
| ATM straddle EM | (CE+PE)_ATM / spot | Remaining move = EM − already-travelled. |
| Max pain | Standard OI payout min | **Expiry session only**, last 90 minutes. Hide on other days. |

### 5.2 Flow layer (today’s river)

For each strike × side (CE/PE):

```
oi_added    = OI - prev_OI          # session, from Fyers prev_oi / oich
vol         = today's option volume
vol_oi      = vol / max(OI_open, 1)  # OI at start ≈ OI - oi_added if oi_added>0
px_chg      = option LTP % change
iv          = leg IV
iv_chg      = vs previous harvest IV if stored
delta, gamma, vega, theta from Fyers greeks=1
```

Classify **each hot strike** (not the whole chain):

```
if oi_added > +size_floor:
    if px_chg > +px_eps:   BUY     (long buildup on that option)
    elif px_chg < -px_eps: WRITE   (short buildup / writing)
    else:                  ADD_UNCLEAR
elif oi_added < -size_floor:
    if px_chg > +px_eps:   COVER   (short covering of that option)
    elif px_chg < -px_eps: UNWIND  (long unwinding)
    else:                  EXIT_UNCLEAR
```

`px_eps` must be in **vol points of the option**, not 0.1%. ATM weeklies need a larger tick; OTM needs % . Use `max(1 tick, 0.5 × ATR_of_option or 3% of LTP)`.

A chain-level intent is the **dominant hot cluster**, not a vote of 40 strikes.

Dominance score:

```
score(cluster) = |oi_added| × max(vol, 1) × (1 + 0.5×1_{vol/OI>2}) × |delta|
```

Winner must beat the runner-up by **≥ 1.35×** or the chain is CONFLICT / PIN.

### 5.3 Futures / spot layer

Stocks: refuse a directional card if futures snapshot is missing.

```
fut_price_up + fut_OI_up     LONG_BUILD
fut_price_down + fut_OI_up   SHORT_BUILD
fut_price_up + fut_OI_down   SHORT_COVER
fut_price_down + fut_OI_down LONG_UNWIND
```

Agreement table (the actual “stock–option relation”):

| Option intent | Futures | Spot vs VWAP | Allowed card |
| :--- | :--- | :--- | :--- |
| BUY_CE | LONG_BUILD | above or reclaim | LONG CE / futures long |
| BUY_CE | SHORT_BUILD | any | NO — hedge or trap |
| WRITE_PE | LONG_BUILD | holding | Support write / bull put / long |
| WRITE_CE | SHORT_BUILD | failing | Resistance write / bear call / short |
| BUY_PE | SHORT_BUILD | below | SHORT / PE |
| WRITE_CE + WRITE_PE | either | inside walls | RANGE / PIN — iron / wait |
| VOL_EXPLODE both wings | any | any | EVENT — no direction |

### 5.4 Decision layer (one primary)

Priority (first match wins):

1. QUIET — L0 fail or nothing hot.
2. PIN — both walls live, GEX+ , EM small, spot inside.
3. VOL_EXPLODE — both wings hot or straddle IV shock, no side.
4. BUY_CE / BUY_PE — explosion ingredients + futures agree.
5. WRITE_CE / WRITE_PE — live wall being built, premium down, used for **fade / range**, not “buy the other side blindly.”
6. UNWIND_* — WATCH only.
7. Else WATCH if one layer hot but others disagree.

TRADEABLE only for 4, or for 5 when the trade is explicitly a **defined-risk write** (we probably still want directional *buy* cards for the product, so WRITE setups are WATCH unless the user asks for selling).

---

## 6. Tag system to implement (replaces OI / VOL / SUP / RES)

### 6.1 Middle-pane filters (user-facing)

Keep four buttons, but they must mean **events**, and they must be **orthogonal**.

| Button | Internal event | True when | Typical hit rate |
| :--- | :--- | :--- | :--- |
| **OI** | `OI_SPURT` | max \|ΔOI\| on a strike cluster ≥ p85 of harvest **in-bucket** AND ≥ that name’s size floor. Volume **not** required. | ~10–15% |
| **Vol** | `VOL_SHOCK` | chain vol p90-in-bucket **and** ≥ 1.8× own recent median **and** top-3 strikes ≥ 35% of volume. | ~10% |
| **Support** | `LIVE_PUT_WALL` | concentrated put wall, spot near, **today’s PE cluster is writing or buying into it**, opposite wall not equally live. | ~8–12% |
| **Resistance** | `LIVE_CALL_WALL` | symmetric on calls. | ~8–12% |

AND still works: OI + Support = **spurt ΔOI sitting on a live put wall**. That is a short list. It will not be the bull column.

Optional later buttons (better than squeezing into four): **Buy**, **Write**, **Explode**, **Pin**. Until then, primary intent can show as a **single chip** under the name (`WRITE CE`, `BUY PE`, `PIN`) instead of four flags.

### 6.2 Display chips (under the name)

Show **only true rare chips**, max 2:

- Intent chip: `BUY CE` / `WRITE PE` / `PIN` / `EXPLODE`
- Size chip: `OI` or `VOL` or `OI+VOL` only if the size event fired
- Do **not** also print SUP and RES. Location is either in the intent (`WRITE CE @ 2400`) or omitted.

### 6.3 Quantile engine (the anti-junk core)

Every boolean is a **percentile in today’s harvest, inside a liquidity bucket** (INDEX / HEAVY / REST).

```
For metric m in {chain_vol, max_abs_dOI, vol_oi_hot, gamma_at_wall, delta_notional}:
    tag_m = m >= percentile(m, 85, universe=same_bucket)
```

Absolute floors remain as **minimums so junk 5k prints on illiquids don’t win a percentile**. They are not sufficient.

**Calibration target after one live session:** each of the four buttons returns a **different** top-20, overlap of all four < 5 names.

If overlap is high, raise percentiles, tighten “near” to 1 step, and require live ΔOI on walls.

### 6.4 Exploding-option scanner (new middle mode or a fifth logic)

A name is `EXPLODE` if:

```
hot strike:
  vol/OI >= 2.5
  vol >= 3 × median_leg_vol of this chain
  |delta| in [0.15, 0.45] OR 2–10% OTM
  DTE <= 14 (stocks) / current expiry (index)
  px_chg agrees with buy (or IV up)
  delta_notional in top decile of harvest
concentration:
  that cluster >= 35% of chain volume
not:
  opposite wing within 0.75× of the same score
```

This is the list that should feel like Opstra UOA / Unusual Whales “this contract is on fire,” not “this stock has an option chain.”

---

## 7. Greeks: what to compute from Fyers, what to derive

### 7.1 Use from the chain (already available)

Fyers option-chain v3 with `greeks=1`:

- `delta, gamma, theta, vega, iv` per CE/PE
- `oi, prev_oi / oich, volume, ltp, chg`

**Do not ignore IV and delta.** The screenshot chain shows IV as `—` on many legs — if the API is blank, compute IV from LTP via BS; if both blank, **do not pretend skew is 0**. Show `IV n/a` and veto skew-based tags.

### 7.2 Must compute ourselves

| Object | Inputs | Notes |
| :--- | :--- | :--- |
| GEX per strike | gamma, OI, spot, lot | Need lot size table (index vs stock). |
| DEX per strike | delta, OI, spot, lot | Dealer directional inventory proxy. |
| Delta-notional of **volume** | delta, **today volume**, lot | Today’s pressure, not the stock of OI. |
| 25Δ RR | interpolate IV vs delta on each wing | If we only have 14 strikes, interpolate. |
| ATM EM | ATM CE+PE LTP | Remaining move vs session range. |
| Own-history z | store chain_vol, ATM IV, max_dOI per name per session | **This is the anti-junk database.** Without it, everything is absolute. |

### 7.3 Lot / multiplier

NSE stock options are lot-sized. GEX/DEX without lot is wrong by 10–50× across names. Keep a static lot map from the Fyers symbol master; refresh daily.

### 7.4 Vanna / charm

Phase 2. Need IV snapshot t-1. Until then, **proxy vanna** with: ATM IV change today × sign(net DEX). If IV crush and net short-delta-to-customers, expect dealer buyback. Label as `IV_FLOW`, not a fake vanna number.

---

## 8. Stock–option relation: concrete rules

The product question is: **does this option print change what we do in the stock / in the option?**

```
LEAD (option → stock) when EXPLODE + BUY + futures not opposing
    + spot has moved < 50% of EM since the shock
    → trade: option (high convexity) or stock/futures (if IV too rich)

HEDGE (stock → option) when BUY_PE while futures LONG_BUILD
    → do not short the stock; someone is protecting a long
    → no directional card; maybe note "collar"

WRITE (inventory) when WRITE_CE at call wall, premium down, +GEX
    → expect pin / fade into wall
    → do not buy CE into the wall
    → possible short / PUT debit only if futures SHORT_BUILD

PIN when GEX+ , both walls live, DTE small, EM tight
    → do not buy premium
    → WAIT / iron only

SQUEEZE WATCH when BUY_CE cluster just above spot, −GEX or flip nearby,
    call-wing IV up, concentrated gamma
    → do not fade; trail if long; wait for through-wall then momentum
```

**Futures are the tie-breaker for Indian stocks.** Options without futures are a rumor.

---

## 9. Data we already have vs data we must persist

| Have (Fyers harvest) | Missing for quant tags | Persist |
| :--- | :--- | :--- |
| Full chain OI, ΔOI, volume, LTP, greeks/IV | Own 5–20 session medians | `chain_vol`, `atm_iv`, `max_dOI`, `pcr` per symbol per day |
| Spot, sometimes VWAP/ATR | Intraday OI spurts (3-min) | Harvest is 3 min — **use consecutive harvests as “spurt”** (ΔOI between harvest t-1 and t, not only vs yesterday) |
| Futures sometimes | Aggressor / sweep | Cannot have. Do not fake. |
| One expiry (nearest) | Next expiry / rolls | Second chain call is expensive (1/min/underlying). On index only, optional. |
| — | FII/DII participant OI | NSE EOD; useful overnight, not intraday |

**Intra-harvest ΔOI** (today 11:00 vs today 10:00) is closer to MarketNetra’s “spurt” than vs yesterday. Yesterday ΔOI is the **session total**. Both are useful; they are different tags:

- `SESSION_DOI` — vs prev_oi (yesterday)
- `SPURT_DOI` — vs last harvest digest (intraday)

Exploding options during the day show up first as `SPURT_DOI` + volume. End-of-day confirmation is `SESSION_DOI` persistence.

This matches US “volume today, OI tomorrow” with a faster clock.

---

## 10. Ranking / scores (replace setup_score 0–100 as a mash)

Split scores. One mash created the screenshot (everything is 70–82).

| Score | Range | Meaning |
| :--- | :--- | :--- |
| `explode_score` | 0–100 | Ingredients in §4.1. Independent of TRADEABLE. |
| `wall_score` | 0–100 | Live wall quality (concentration × nearness × today’s activity). |
| `agree_score` | −100–100 | Option intent vs futures vs spot. 0 = missing/conflict. |
| `setup_score` | 0–100 | Only for names that pass vetoes: 0.45×explode + 0.25×wall + 0.30×agree. |

Bull/bear columns sort by `setup_score` among **agreed directionals**.  
Middle explode/OI/Vol lists sort by `explode_score` or the metric of the filter.  
Do not sort the Resistance filter by the same score as Bullish.

---

## 11. Worked read of the screenshot (TCS)

Using only what the image shows:

- Spot ~ 2,340 (card wants CE 2340), put wall 2300, call wall 2400, γ-wall 2300, max pain 2320.
- PCR 0.79 → more call OI than put OI → **call-writing inventory**, not a bullish PCR.
- Call volume on the visible grid is tiny (0, 0, 4275, 225, 675…). Put volume is large (1.6L–13.9L) with mixed ΔOI (unwinds and +97k at 2160 PE).
- Futures UNKNOWN.
- IV skew printed 0.

**Honest desk read:** put-side is the live tape; call-side is not exploding; futures missing; this is **not** a BUY CE 2340. It may be a **range 2300–2400** (PIN / walls) with put activity below. Primary tag should be `PIN` or `WRITE_PE` (if the put adds are writing), **not** `OI VOL SUP RES` and not TRADEABLE long.

IDEA with 2,825L vol and 10.98L ΔOI **might** deserve `VOL_SHOCK` + a single intent, if concentration and premium direction agree. It should not share the same four chips as TCS.

That is the difference between junk analysis and intention.

---

## 12. Scanner landscape — what to copy, what to ignore

| Scanner | Copy | Ignore / cannot copy on NSE |
| :--- | :--- | :--- |
| Opstra UOA | Per-**contract** vol vs OI, then open the chart | US-style dark pool |
| Sensibull OI vs time | Wall migration, custom window | Treating chain as a shop |
| Quantsapp unusual | Separate signals: price / OI / volume / IV | 40 overlapping scanners |
| NiftyTrader screener | Combine: vol>2× ADV **and** ΔOI top decile **and** IV +5pts | Single-filter dumps |
| Unusual Whales | Opening, premium, OTM, DTE, multi-leg filter, score | Sweep ISO, $ premium in USD, ETF 0DTE spam |
| SpotGamma | Regime first, walls second, squeeze scanner third | HIRO (needs tick flow) |
| Cheddar / FlowAlgo | Ask-side, opening, unusual vs **own** history | Blocks/sweeps |
| Barchart UOA | Simple vol/OI cut as **pre-filter** | Using it as the product |
| GammaGrid open source | GEX heatmap, OI delta between snapshots, unusual vs own history | Assuming dealer sign is truth |

**Indian product that matches our data constraint:** Opstra UOA + Sensibull OI-vs-time + NiftyTrader 3-filter AND + SpotGamma regime. That stack is implementable on Fyers harvests.

---

## 13. Implementation plan (still no code in this file)

When we implement, do it in this order. Each step is testable with a harvest snapshot.

### Step A — Kill always-on tags

- Compute tags only as **percentile events** (§6.3).
- Mutual exclusion: PIN xor SUP xor RES.
- OI independent of VOL.
- Persist `screen` over **all** grades including QUIET.
- UI: max two chips; primary intent text (`WRITE CE @ 2400`).

**Acceptance:** Resistance filter < 20% of book. Overlap of all four filters < 5 names. Screenshot-style `OI VOL SUP RES` rows = 0.

### Step B — Writing vs buying

- Classify every hot strike with premium Δ + ΔOI (§5.2).
- Chain intent = dominant cluster with 1.35× margin.
- No BUY card on WRITE.

**Acceptance:** a put-wall with premium down is `WRITE_PE`, not a long.

### Step C — Explode scanner

- Strike vol/OI, concentration, delta-notional, OTM band, IV direction.
- Rank middle pane by `explode_score` when Vol or a dedicated mode is on.

**Acceptance:** IDEA-like names surface; TCS-like pin names do not.

### Step D — GEX / DEX / EM / RR

- Lot-aware GEX profile, flip, remaining EM, 25Δ RR.
- Hide max pain except expiry window.
- Veto cards when futures missing (stocks) or EM already spent.

**Acceptance:** TCS with futures UNKNOWN cannot be TRADEABLE. Skew 0 only if IV missing, shown as n/a.

### Step E — Own-history store

- Per symbol, last 20 sessions + last 30 harvests today: chain_vol, atm_iv, max_dOI, pcr.
- Z-scores vs self.

**Acceptance:** NIFTY is not “high vol” every day. A REST name that 3× its own vol **is**.

### Step F — Intra-harvest spurts

- Digest legs every harvest; ΔOI and Δvol vs **previous harvest**, not only vs yesterday.
- Spurt tag for 3–5× own add-rate in one interval.

This is the closest we get to “catching the explosion **as it happens**” on a 3-minute quota.

### Tests that must exist before UI claims

1. Flat OI chain → no SUP, no RES, no OI, no VOL.
2. Concentrated put wall, quiet volume, large ΔOI, premium down → OI + Support + WRITE_PE, not VOL, not RES.
3. High equal volume both wings → VOL_EXPLODE only.
4. High volume every day historically, average today → no VOL.
5. Call buy OTM 5%, vol/OI 4, futures long buildup → EXPLODE + BUY_CE.
6. Call buy OTM, futures short buildup → no TRADEABLE.
7. Both walls live, spot mid, +GEX → PIN only.
8. Percentile: in a 100-name synthetic harvest, each tag ≤ 15 names.

---

## 14. Explicit non-goals (so we do not rebuild the zoo)

- Do not add RSI, VWAP-only, 7/200, VAT, confluence mash as selectors.
- Do not fake US sweeps on NSE.
- Do not use max pain as a daily target.
- Do not use raw PCR as a buy/sell.
- Do not auto-stamp four tags so the filter “has results.”
- Do not make TRADEABLE the same set as “has a wall.”
- Do not harvest extra expiries for all 187 names (quota). Index + top 10 explode names only if needed.

---

## 15. One-page operating doctrine

1. **The chain is a map of writers and a tape of today’s prints.** Those are different.
2. **A tag must be rare, exclusive, and quantified against self and peers.**
3. **Exploding options are concentrated, new, aggressive, convex prints** measured in **delta-notional**, confirmed by the next OI snapshot and by futures.
4. **Greeks matter in this order:** delta-notional of volume, gamma regime, IV/skew, then vanna/charm.
5. **Stock follows options only when the print is a lead (buy + new + liquid + futures agree) and the expected move is not spent.** Otherwise the option is a hedge or a write.
6. **If the book is quiet or conflicted, the output is QUIET.** A full screen of 70+ scores is a bug.
7. **Bull/bear = agreed directional setups. Middle = event scanner.** If they show the same names, the logic has collapsed again.

---

## 16. Source list (for later rereads)

**Flow / UOA:** Market Rebellion Heat Seeker; Unusual Whales flow docs + Sandford walkthroughs; Cheddar Flow unusual-volume practice; Alpha Suite / CrossVol / StrikeWatch UOA; TradeAlgo scanner guide; iPresage methodology; Barchart / CBOE vol-OI; Optionomics unusual-activity badges; FlashAlpha sweep coalescing.

**GEX / greeks:** SpotGamma (GEX, walls, squeeze, vanna/charm, how to trade levels); Unusual Whales spot-gamma heatmap; QuantWheel; GEXMetrix; ExpireWorthless GEX formula; VannaCharm; GammaSonar; GEXRadar OPEX vanna/charm; FlashAlpha DEX vs GEX; TradeEcho reservoir vs river; GammaGrid (open source).

**Indian chain:** NiftyTrader OI + chain guides; Sensibull OI page; Opstra UOA (Definedge); Quantsapp scanners; Stoxra weekly expiry + max pain; MarketNetra OI spurts + expiry day; NiftyDesk flow; Stolo strike OI; ArthaLearn OI matrix; NSE participant OI.

**IV / surface:** 25Δ risk reversal (CuteMarkets, Derivasys, Sharpnel, StrikeWatch); ATM straddle expected move; term structure contango/backwardation; IV rank vs own 30d (OptionVisualizer).

**Lead–lag:** Patel & Putniņš (options ~25% of discovery); index futures/options lead cash; near-ATM informed trading in liquid names only; delta-hedge tape at 50–100ms (US).

**X:** @unusual_whales, Anthony Sandford, SpotGamma, GammaFlowSPY (regime discipline).

---

*End of research dump. Next implementation should start at §13 Step A and not ship another four-tag screen until the acceptance tests in that section pass on a live harvest.*
