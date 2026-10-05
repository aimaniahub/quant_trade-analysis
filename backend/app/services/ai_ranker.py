"""OpenRouter ranker: news → ≤5 F&O names. Model/key come from env."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import get_settings
from app.services.news_aliases import (
    count_mentions,
    fno_short_names,
    is_index,
    resolve_name,
    short_name,
)
from app.utils.market_hours import IST

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a filter for Indian NSE F&O intraday options.
You do NOT pick trades. You do NOT pick strikes. You do NOT invent tickers.

You will receive:
- TODAY_IST
- FNO_NAMES: allowed short names only
- ARTICLES: id, time, category, title, body

Task: choose up to 5 DISTINCT F&O names that can reasonably MOVE TODAY because of these articles.

Rules:
1. name MUST be copied from FNO_NAMES. If the company is not in FNO_NAMES, skip it.
2. Prefer company-specific catalysts (order, earnings, legal, M&A, rating+number).
3. If the same name appears in 2+ articles, it is stronger — still only one slot.
4. Macro (crude, RBI, GIFT, Nifty) goes to index_bias, NOT to five random oil/bank names.
5. Drop essays, IPOs of unlisted firms, tax explainers, entertainment, 2030 outlooks.
6. news must be ≤ 18 words, a fact from the article, no buy/sell/target advice.
7. intent is a headline hint, not a trade. Mixed order+Sell rating = UNCLEAR.
8. Return AT MOST 5. Returning 2 good names is better than padding.
9. Call submit_top5. No extra prose.
"""

SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_top5",
        "description": "Submit up to 5 F&O names for today plus index context.",
        "parameters": {
            "type": "object",
            "properties": {
                "index_bias": {
                    "type": "string",
                    "enum": ["RISK_ON", "RISK_OFF", "MIXED"],
                },
                "index_why": {"type": "string"},
                "picks": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "rank": {"type": "integer"},
                            "name": {"type": "string"},
                            "news": {"type": "string"},
                            "intent": {
                                "type": "string",
                                "enum": ["BULLISH", "BEARISH", "VOL", "UNCLEAR"],
                            },
                            "event_type": {
                                "type": "string",
                                "enum": [
                                    "ORDER_WIN",
                                    "EARNINGS",
                                    "RATING",
                                    "M_AND_A",
                                    "LEGAL",
                                    "GUIDANCE",
                                    "MACRO_INDEX",
                                    "OTHER",
                                ],
                            },
                            "article_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["name", "news"],
                    },
                },
            },
            "required": ["picks"],
        },
    },
}

_ADVICE = re.compile(r"\b(buy|sell|accumulate|target|cmp)\b", re.I)


def _clip_news(text: str) -> str:
    words = re.sub(r"\s+", " ", _ADVICE.sub("", text or "")).strip().split()
    return " ".join(words[:18])


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


def parse_model_payload(resp: Dict[str, Any]) -> Dict[str, Any]:
    choice = ((resp.get("choices") or [{}])[0]) or {}
    msg = choice.get("message") or {}
    for call in msg.get("tool_calls") or []:
        fn = (call.get("function") or {}) if isinstance(call, dict) else {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        if isinstance(args, dict):
            return args
    content = msg.get("content")
    if isinstance(content, list):
        content = " ".join(
            str(part.get("text") or part) if isinstance(part, dict) else str(part)
            for part in content
        )
    obj = _extract_json(str(content or ""))
    return obj or {"picks": []}


def build_user_payload(articles: List[Dict[str, Any]]) -> str:
    names = ", ".join(fno_short_names())
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
    lines = [f"TODAY_IST: {now}", f"FNO_NAMES: {names}", "", "ARTICLES:"]
    budget = 11000
    used = 0
    for art in articles:
        block = (
            f"ID {art.get('id')}\n"
            f"TIME {art.get('ts_ist')}\n"
            f"CAT {art.get('category')}\n"
            f"TITLE {art.get('title')}\n"
            f"BODY {(art.get('body') or '')[:420]}\n"
        )
        if used + len(block) > budget:
            break
        lines.append(block)
        used += len(block)
    return "\n".join(lines)


def _openrouter_chat(messages: List[Dict[str, Any]], use_tools: bool) -> Dict[str, Any]:
    settings = get_settings()
    key = (settings.openrouter_api_key or "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    model = (settings.openrouter_model or "google/gemma-4-31b-it:free").strip()
    base = (settings.openrouter_base_url or "https://openrouter.ai/api/v1").rstrip("/")
    body: Dict[str, Any] = {
        "model": model,
        "temperature": 0.1,
        "max_tokens": 1200,
        "messages": messages,
        "reasoning": {"enabled": False},
    }
    if use_tools:
        body["tools"] = [SUBMIT_TOOL]
        body["tool_choice"] = {"type": "function", "function": {"name": "submit_top5"}}
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://optiongreek.local",
        "X-Title": "OptionGreek AI+Chain",
    }
    with httpx.Client(timeout=90.0) as client:
        r = client.post(f"{base}/chat/completions", headers=headers, json=body)
        if r.status_code >= 400:
            raise RuntimeError(f"OpenRouter HTTP {r.status_code}: {r.text[:240]}")
        return r.json()


def rank_articles(articles: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], str]:
    user = build_user_payload(articles)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
    last_err: Optional[Exception] = None
    raw: Dict[str, Any] = {}
    for use_tools in (True, False):
        try:
            raw = _openrouter_chat(messages, use_tools=use_tools)
            parsed = parse_model_payload(raw)
            if parsed.get("picks") is not None:
                return parsed, str(raw.get("model") or get_settings().openrouter_model)
        except Exception as exc:
            last_err = exc
            logger.info("openrouter tools=%s failed: %s", use_tools, exc)
            continue
    if last_err:
        raise last_err
    return {"picks": []}, str(raw.get("model") or "")


def validate_picks(
    parsed: Dict[str, Any],
    articles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    by_id = {str(a.get("id")): a for a in articles}
    picks_in = parsed.get("picks") or []
    if not isinstance(picks_in, list):
        picks_in = []
    rejected: List[Dict[str, str]] = []
    seen_sym: Dict[str, Dict[str, Any]] = {}
    for i, row in enumerate(picks_in):
        if not isinstance(row, dict):
            continue
        raw_name = str(row.get("name") or "").strip()
        event_type = str(row.get("event_type") or "OTHER").upper()
        if event_type == "MACRO_INDEX":
            continue
        symbol = resolve_name(raw_name)
        if not symbol:
            rejected.append({"raw": raw_name, "reason": "not_fno"})
            continue
        if is_index(symbol):
            continue
        ids = [str(x) for x in (row.get("article_ids") or []) if str(x) in by_id]
        if not ids:
            # attach articles that mention the name
            for art in articles:
                blob = f"{art.get('title')} {art.get('body')}"
                if count_mentions(blob, symbol):
                    ids.append(str(art.get("id")))
        news = _clip_news(str(row.get("news") or ""))
        if not news and ids:
            news = _clip_news(str(by_id[ids[0]].get("title") or ""))
        intent = str(row.get("intent") or "UNCLEAR").upper()
        if intent not in ("BULLISH", "BEARISH", "VOL", "UNCLEAR"):
            intent = "UNCLEAR"
        repeat_n = 0
        for art in articles:
            blob = f"{art.get('title')} {art.get('body')}"
            if count_mentions(blob, symbol):
                repeat_n += 1
        rec = {
            "rank": int(row.get("rank") or i + 1),
            "symbol": symbol,
            "name": short_name(symbol),
            "news": news,
            "news_intent": intent,
            "event_type": event_type if event_type else "OTHER",
            "repeat_n": max(repeat_n, len(ids), 1),
            "hot": True,
            "article_ids": ids,
        }
        prev = seen_sym.get(symbol)
        if prev is None or rec["repeat_n"] > prev["repeat_n"]:
            seen_sym[symbol] = rec
    ordered = sorted(
        seen_sym.values(),
        key=lambda r: (-int(r.get("repeat_n") or 0), int(r.get("rank") or 99)),
    )[:5]
    for i, rec in enumerate(ordered, 1):
        rec["rank"] = i
    why = _clip_news(str(parsed.get("index_why") or parsed.get("index_context") or ""))
    bias = str(parsed.get("index_bias") or "MIXED").upper()
    if bias not in ("RISK_ON", "RISK_OFF", "MIXED"):
        bias = "MIXED"
    return {
        "picks": ordered,
        "rejected": rejected[:12],
        "index_context": {
            "bias": bias,
            "why": why,
            "follow": ["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"],
        },
    }
