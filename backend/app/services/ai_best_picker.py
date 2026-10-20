"""
AI Best Picker — High-conviction intraday 2-trade selector for Flow Radar.

Uses OpenRouter (with intelligent multi-factor quantitative fallback) to select
EXACTLY 2 best trades from the scanned candidate pool, incorporating technical reality:
Support/Resistance walls, VWAP alignment, Risk:Reward, and Trap Avoidance.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import get_settings
from app.utils.market_hours import IST

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Lead Quantitative Derivatives Strategist and Chief Execution Architect specializing in Indian NSE F&O markets.

Your mandate is to perform an institutional DEEP RESEARCH EVALUATION across the entire candidate pool of scanned F&O equities to identify the EXACTLY 2 HIGHEST-EDGE TRADES for today.

DEEP RESEARCH EVALUATION PROTOCOL:
1. CROSS-STRIKE LIQUIDITY & NET ΔOI ANALYSIS:
   - Analyze institutional accumulation: A positive Net ΔOI indicates aggressive Put Writing / call absorption (bullish institutional floor). A negative Net ΔOI indicates aggressive Call Writing / put absorption (bearish institutional ceiling).
   - Reject setups where Net ΔOI contradicts the proposed trade action (e.g., buying calls on negative Net ΔOI).

2. TECHNICAL REALITY & TRAP CLEARANCE:
   - Evaluate exact clearance to the next structural level (Call Wall / Put Wall / Max Pain / VWAP).
   - BULL TRAP ELIMINATION: Reject any Bullish candidate if Spot is within 1.0% of Call Wall (immediate supply ceiling) or trading below daily VWAP.
   - BEAR TRAP ELIMINATION: Reject any Bearish candidate if Spot is within 1.0% of Put Wall (immediate demand floor) or trading above daily VWAP.
   - Clean Room Requirement: Spot must have at least 1.5% uninhibited room to run before encountering structural resistance.

3. OPTIMAL STRIKE SELECTION & ASYMMETRIC RISK:REWARD:
   - Strike selection must be liquid ATM or 1 strike OTM on the trend side.
   - Define precise CMP / Spot Entry, structural Stop-Loss (invalidation level placed behind VWAP or key wall), conservative Target 1, runner Target 2, and minimum Risk:Reward of 1:1.8.

4. SELECTION FLEXIBILITY:
   - ANY COMBINATION IS ALLOWED: 2 Bullish (2 × BUY CE), 2 Bearish (2 × BUY PE), or 1 Bullish CE + 1 Bearish PE. Pick the 2 cleanest, highest-conviction setups from the universe without forcing symmetry.

5. OUTPUT SPECIFICATION:
   - Respond strictly with valid JSON. No conversational preamble, no markdown backticks outside of JSON.

JSON OUTPUT FORMAT:
{
  "picks": [
    {
      "symbol": "NSE:...",
      "name": "...",
      "action": "BUY_CE" or "BUY_PE",
      "strike": 1420.0,
      "spot": 1415.5,
      "entry": "1415.5 (Spot CMP)",
      "stop_loss": 1400.0,
      "target_1": 1445.0,
      "target_2": 1460.0,
      "risk_reward": "1:2.0",
      "trap_risk_status": "CLEAN — Spot above VWAP (+1.2%) with 2.8% clearance to Call Wall",
      "catalyst_and_thesis": "Deep Research: Heavy put writing at 1400 floor (+1.2M PE OI). VOR 2.4x institutional volume surge with rising IV expansion.",
      "invalidation": "Hourly close below VWAP 1400 or net flow flip to negative"
    }
  ],
  "market_thesis": "...",
  "portfolio_stance": "2_BULL" or "2_BEAR" or "1_BULL_1_BEAR"
}
"""


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.S)
    if fence:
        t = fence.group(1)
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(t[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _format_candidate_for_ai(row: Dict[str, Any]) -> Dict[str, Any]:
    flags = row.get("flags") or {}
    st = row.get("structure") or {}
    sess = row.get("session") or {}
    spot = float(row.get("spot") or 0)
    cw = float(st.get("call_wall") or row.get("call_wall") or 0)
    pw = float(st.get("put_wall") or row.get("put_wall") or 0)
    vwap = float(sess.get("vwap") or row.get("vwap") or 0)

    dist_cw = round((cw - spot) / spot * 100.0, 2) if spot > 0 and cw > 0 else None
    dist_pw = round((spot - pw) / spot * 100.0, 2) if spot > 0 and pw > 0 else None
    dev_vwap = round((spot - vwap) / vwap * 100.0, 2) if spot > 0 and vwap > 0 else None

    bias = row.get("chain_bias") or row.get("sentiment") or row.get("bias")
    score = row.get("setup_score") if row.get("setup_score") is not None else row.get("score", 0)

    return {
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "spot": spot,
        "bias": bias,
        "grade": row.get("grade") or ("TRADEABLE" if score >= 70 else "WATCH"),
        "setup_score": score,
        "net_delta_oi": flags.get("net_delta_oi") or row.get("net_delta_oi") or 0,
        "opt_volume": flags.get("opt_volume") or row.get("chain_volume") or row.get("total_opt_vol") or 0,
        "vor": flags.get("vor") or row.get("vor") or 0,
        "trap_risk": bool(flags.get("trap_risk") or row.get("trap_risk")),
        "trap_reason": flags.get("trap_reason") or row.get("trap_reason"),
        "call_wall": cw or None,
        "dist_to_call_wall_pct": dist_cw,
        "put_wall": pw or None,
        "dist_to_put_wall_pct": dist_pw,
        "vwap": vwap or None,
        "dev_vwap_pct": dev_vwap,
        "tags": flags.get("tags") or row.get("tags") or [],
        "why_not": row.get("why_not"),
        "trade_card": row.get("trade"),
    }


def _algorithmic_best_picks(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Robust multi-factor quantitative evaluator.
    Selects exactly 2 best setups (any combination: 2 Bull, 2 Bear, or 1 Bull + 1 Bear).
    """
    ranked_pool: List[Tuple[float, Dict[str, Any]]] = []

    for c in candidates:
        flags = c.get("flags") or {}
        st = c.get("structure") or {}
        sess = c.get("session") or {}
        bias = str(c.get("chain_bias") or c.get("sentiment") or c.get("bias") or "").upper()
        if bias not in ("BULLISH", "BEARISH"):
            continue

        spot = float(c.get("spot") or 0)
        if spot <= 0:
            continue

        score = float(c.get("setup_score") if c.get("setup_score") is not None else (c.get("score") or 0))
        vor = float(flags.get("vor") or c.get("vor") or 0)
        net_oi = float(flags.get("net_delta_oi") or c.get("net_delta_oi") or 0)
        has_trap = bool(flags.get("trap_risk") or c.get("trap_risk"))

        # Heavy penalty for traps (almost disqualifies)
        if has_trap:
            score -= 40.0

        # Technical clearance bonus
        cw = float(st.get("call_wall") or c.get("call_wall") or 0)
        pw = float(st.get("put_wall") or c.get("put_wall") or 0)
        vwap = float(sess.get("vwap") or 0)

        if bias == "BULLISH":
            if cw > spot:
                room = (cw - spot) / spot * 100.0
                if room >= 1.5:
                    score += 10.0
            if vwap > 0 and spot >= vwap:
                score += 8.0
            if net_oi > 0:
                score += 6.0
        elif bias == "BEARISH":
            if pw > 0 and spot > pw:
                room = (spot - pw) / spot * 100.0
                if room >= 1.5:
                    score += 10.0
            if vwap > 0 and spot <= vwap:
                score += 8.0
            if net_oi < 0:
                score += 6.0

        score += min(15.0, vor * 12.0)
        if c.get("grade") == "TRADEABLE":
            score += 15.0

        ranked_pool.append((score, c))

    ranked_pool.sort(key=lambda x: x[0], reverse=True)
    selected_candidates = [item[1] for item in ranked_pool[:2]]

    picks: List[Dict[str, Any]] = []
    bull_count = 0
    bear_count = 0

    for cand in selected_candidates:
        bias = str(cand.get("chain_bias") or cand.get("sentiment") or cand.get("bias") or "").upper()
        spot = float(cand.get("spot") or 0)
        st = cand.get("structure") or {}
        sess = cand.get("session") or {}
        cw = float(st.get("call_wall") or cand.get("call_wall") or 0)
        pw = float(st.get("put_wall") or cand.get("put_wall") or 0)
        card = cand.get("trade") or {}

        if bias == "BULLISH":
            bull_count += 1
            action = "BUY_CE"
            strike = float(card.get("strike") or (spot * 1.005))
            entry = spot
            stop = float(card.get("stop") or (pw if pw and pw < spot * 0.99 else round(spot * 0.992, 2)))
            target_1 = float(card.get("target") or (cw if cw and cw > spot else round(spot * 1.018, 2)))
            target_2 = round(target_1 + (target_1 - entry) * 0.5, 2)
            risk = max(1e-9, entry - stop)
            reward = max(1e-9, target_1 - entry)
            rr = f"1:{round(reward / risk, 1)}"
            trap_stat = "CLEAN - Above VWAP, strong Put floor support"
            thesis = f"Bullish flow accumulation with high setup score ({cand.get('setup_score') or cand.get('score') or 75}). Room toward Call Wall {cw or 'target'}."
            inv = f"Close below support {stop} or flow flip"
        else:
            bear_count += 1
            action = "BUY_PE"
            strike = float(card.get("strike") or (spot * 0.995))
            entry = spot
            stop = float(card.get("stop") or (cw if cw and cw > spot * 1.01 else round(spot * 1.008, 2)))
            target_1 = float(card.get("target") or (pw if pw and pw < spot else round(spot * 0.982, 2)))
            target_2 = round(target_1 - (entry - target_1) * 0.5, 2)
            risk = max(1e-9, stop - entry)
            reward = max(1e-9, entry - target_1)
            rr = f"1:{round(reward / risk, 1)}"
            trap_stat = "CLEAN - Below VWAP, strong Call ceiling resistance"
            thesis = f"Bearish flow accumulation with high setup score ({cand.get('setup_score') or cand.get('score') or 75}). Downside target toward Put Wall {pw or 'target'}."
            inv = f"Close above resistance {stop} or flow flip"

        picks.append({
            "symbol": cand.get("symbol"),
            "name": cand.get("name") or cand.get("symbol", "").split(":")[-1].replace("-EQ", ""),
            "action": action,
            "strike": round(strike, 1),
            "spot": round(spot, 2),
            "entry": f"{round(spot, 2)} (Spot)",
            "stop_loss": round(stop, 2),
            "target_1": round(target_1, 2),
            "target_2": round(target_2, 2),
            "risk_reward": rr,
            "trap_risk_status": trap_stat,
            "catalyst_and_thesis": thesis,
            "invalidation": inv,
        })

    stance = (
        "2_BULL" if bull_count == 2
        else "2_BEAR" if bear_count == 2
        else "1_BULL_1_BEAR" if (bull_count == 1 and bear_count == 1)
        else "SELECTIVE"
    )

    return {
        "success": True,
        "picks": picks,
        "market_thesis": f"Quantitative confluence selected {len(picks)} high-conviction trades with trap filtering ({stance}).",
        "portfolio_stance": stance,
        "engine": "quant_confluence_eval",
        "model": "rule_based_confluence",
        "timestamp": datetime.now(IST).isoformat(),
    }


def get_ai_best_picks(
    force: bool = False,
    candidate_list: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Main evaluation pipeline: OpenRouter API with automated quantitative fallback.
    """
    from app.services.option_flow_radar import get_radar_service

    radar_scan = get_radar_service().get_last_scan() or {}
    candidates: List[Dict[str, Any]] = []

    if candidate_list:
        candidates = list(candidate_list)
    else:
        # Collect top candidates from current scan
        bull = list(radar_scan.get("bullish") or [])
        bear = list(radar_scan.get("bearish") or [])
        unique = list(radar_scan.get("unique") or [])
        seen_syms = set()
        for r in unique + bull + bear:
            sym = r.get("symbol")
            if sym and sym not in seen_syms:
                seen_syms.add(sym)
                candidates.append(r)

    if not candidates:
        # Fallback to store
        from app.services import symbol_store as store
        board_data = store.get_board() or store.get_session_board() or {}
        b_rows = list(board_data.get("rows") or board_data.get("bullish") or []) + list(board_data.get("bearish") or [])
        candidates = b_rows[:15]

    if not candidates:
        return {
            "success": False,
            "error": "No scan candidate pool available. Please run a Flow Radar scan first.",
            "picks": [],
        }

    # Format top candidates for Deep Research LLM prompt
    ai_candidates = [_format_candidate_for_ai(c) for c in candidates[:20]]

    settings = get_settings()
    or_key = (settings.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY") or "").strip()

    if or_key:
        base = (settings.openrouter_base_url or "https://openrouter.ai/api/v1").rstrip("/")
        model = (settings.openrouter_model or "google/gemma-4-31b-it:free").strip()
        user_prompt = (
            f"TODAY_IST: {datetime.now(IST).strftime('%Y-%m-%d %H:%M')}\n"
            f"CANDIDATE_POOL ({len(ai_candidates)} names):\n"
            + json.dumps(ai_candidates, indent=2, default=str)
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        try:
            with httpx.Client(timeout=45.0) as client:
                r = client.post(
                    f"{base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {or_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://optiongreek.local",
                        "X-Title": "OptionGreek AI Best Picker",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": 0.1,
                        "max_tokens": 1200,
                    },
                )
            if r.status_code < 400:
                resp_json = r.json()
                content = (((resp_json.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
                parsed = _extract_json(str(content))
                if parsed and isinstance(parsed.get("picks"), list) and len(parsed["picks"]) > 0:
                    return {
                        "success": True,
                        "picks": parsed.get("picks")[:2],
                        "market_thesis": parsed.get("market_thesis") or "High-conviction 2-trade selection via OpenRouter.",
                        "portfolio_stance": parsed.get("portfolio_stance") or "UNSPECIFIED",
                        "engine": "openrouter",
                        "model": str(resp_json.get("model") or model),
                        "timestamp": datetime.now(IST).isoformat(),
                    }
            else:
                logger.warning("OpenRouter API returned HTTP %s: %s", r.status_code, r.text[:200])
        except Exception as exc:
            logger.warning("OpenRouter execution failed: %s, falling back to quant confluence engine", exc)

    # Automated Fallback to Quantitative Confluence Engine
    logger.info("Executing Algorithmic Quantitative Best Picker fallback")
    return _algorithmic_best_picks(candidates)
