"""Whalesbook market-news scrape. JustTicks is not used."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://app2.whalesbook1.shop"
NEWS_PATH = "/published-news-collection/v3/free"
SITE = "https://www.whalesbook.com"
CACHE_TTL = 7200
PAGE_LIMIT = 20
MAX_PAGES = 2
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "news_articles.jsonl"

_cache: Tuple[float, List[Dict[str, Any]]] = (0.0, [])

DROP_CATEGORIES = {
    "media and entertainment",
    "personal finance",
    "startups/vc",
    "ipo",
    "mutual funds",
    "world affairs",
    "international news",
    "research reports",
    "stock investment ideas",
}

DROP_TITLE = (
    "ex-dividend",
    "ex dividend",
    "income-tax",
    "income tax refund",
    "wealth management",
    "by 2030",
    "bollywood",
    "casting",
    "ipo size",
    "ipo ",
)

KEEP_HINTS = (
    "order",
    "contract",
    "earnings",
    "profit",
    "result",
    "rating",
    "buyback",
    "merger",
    "acquire",
    "bid",
    "rbi",
    "crude",
    "oil",
    "nifty",
    "bank nifty",
    "guidance",
    "capex",
    "lawsuit",
    "sebi",
    "upgrade",
    "downgrade",
    "q1",
    "q2",
    "q3",
    "q4",
    "fy2",
)


def _headers() -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 OptionGreek/ai-chain",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": SITE,
        "Referer": f"{SITE}/market-news/English/all",
    }


def _norm_article(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    trans = None
    for row in raw.get("translations") or []:
        if str(row.get("language") or "").lower() == "english":
            trans = row
            break
    trans = trans or {}
    aid = str(raw.get("_id") or raw.get("id") or "").strip()
    title = str(trans.get("headline") or raw.get("headline") or "").strip()
    body = str(
        trans.get("shortDescription")
        or raw.get("shortDescription")
        or trans.get("detailedCoverage")
        or ""
    ).strip()
    if not aid or not title:
        return None
    ts = raw.get("createdAt") or raw.get("scrappedAt") or ""
    url = str(raw.get("newsUrl") or raw.get("url") or "")
    if url and url.startswith("/"):
        url = SITE + url
    return {
        "id": aid,
        "url": url,
        "ts_ist": ts,
        "category": str(raw.get("newsType") or raw.get("sector") or "Other"),
        "title": title,
        "body": body[:1200],
        "source": "whalesbook",
    }


def keep_article(art: Dict[str, Any]) -> bool:
    cat = str(art.get("category") or "").lower()
    title = str(art.get("title") or "").lower()
    body = str(art.get("body") or "").lower()
    blob = f"{title} {body}"
    if cat in DROP_CATEGORIES:
        return False
    if any(x in title for x in DROP_TITLE):
        return False
    if "stocks turning ex-dividend" in blob or "stocks trading ex-dividend" in blob:
        return False
    if any(h in blob for h in KEEP_HINTS):
        return True
    if cat in (
        "auto",
        "banking/finance",
        "energy",
        "technology",
        "healthcare/biotech",
        "consumer products",
        "industrial goods/services",
        "telecom",
        "real estate",
        "commodities",
    ):
        return True
    return False


def _append_jsonl(rows: List[Dict[str, Any]]) -> None:
    try:
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = set()
        if DATA_PATH.exists():
            for line in DATA_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()[-400:]:
                try:
                    existing.add(json.loads(line).get("id"))
                except Exception:
                    continue
        with DATA_PATH.open("a", encoding="utf-8") as fh:
            for row in rows:
                if row.get("id") in existing:
                    continue
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("news jsonl skip: %s", exc)


def _live_fetch(limit: int = 40) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=2)
    out: List[Dict[str, Any]] = []
    seen = set()
    with httpx.Client(timeout=20.0, headers=_headers()) as client:
        for page in range(1, MAX_PAGES + 1):
            payload = {
                "endDate": now.isoformat().replace("+00:00", "Z"),
                "startDate": start.isoformat().replace("+00:00", "Z"),
                "language": "English",
                "limit": PAGE_LIMIT,
                "page": page,
                "sector": "All",
            }
            r = client.post(API_BASE + NEWS_PATH, json=payload)
            r.raise_for_status()
            data = r.json() or {}
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                break
            for raw in rows:
                art = _norm_article(raw)
                if not art or art["id"] in seen:
                    continue
                seen.add(art["id"])
                out.append(art)
            if len(out) >= limit:
                break
            if not data.get("hasMore") and page >= int((data.get("pagination") or {}).get("totalPages") or 1):
                break
    return out[:limit]


def _readme_fallback() -> List[Dict[str, Any]]:
    """Parse committed whalesbook/README.md if the live API is down."""
    root = Path(__file__).resolve().parents[3] / "whalesbook" / "README.md"
    if not root.exists():
        return []
    text = root.read_text(encoding="utf-8", errors="ignore")
    items: List[Dict[str, Any]] = []
    blocks = re.split(r"\n## \d+\. ", text)
    for block in blocks[1:]:
        lines = [ln.rstrip() for ln in block.strip().splitlines()]
        if not lines:
            continue
        title = lines[0].strip()
        cat = ""
        url = ""
        date = ""
        body_lines: List[str] = []
        for ln in lines[1:]:
            if ln.startswith("- Category:"):
                cat = ln.split(":", 1)[-1].strip()
            elif ln.startswith("- Link:"):
                url = ln.split(":", 1)[-1].strip()
            elif ln.startswith("- Date:"):
                date = ln.split(":", 1)[-1].strip()
            elif ln.startswith("- "):
                continue
            elif ln.strip():
                body_lines.append(ln.strip())
        aid = ""
        if "/" in url:
            aid = url.rstrip("/").split("/")[-1]
        items.append({
            "id": aid or title[:24],
            "url": url,
            "ts_ist": date,
            "category": cat or "Other",
            "title": title,
            "body": " ".join(body_lines)[:1200],
            "source": "whalesbook-readme",
        })
    return items


def scrape_market_news(force: bool = False, limit: int = 40) -> Tuple[List[Dict[str, Any]], str]:
    """Return (articles, source_tag)."""
    global _cache
    now = time.time()
    if not force and _cache[1] and now - _cache[0] < CACHE_TTL:
        return list(_cache[1]), "cache"
    try:
        rows = _live_fetch(limit=limit)
        if rows:
            _cache = (now, rows)
            _append_jsonl(rows)
            return rows, "live"
    except Exception as exc:
        logger.warning("whalesbook live scrape failed: %s", exc)
    fallback = _readme_fallback()
    if fallback:
        _cache = (now, fallback)
        return fallback, "readme"
    raise RuntimeError("Whalesbook news unreachable")


def prefilter(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    seen_title = set()
    for art in articles:
        title_key = re.sub(r"\s+", " ", (art.get("title") or "").lower())
        if title_key in seen_title:
            continue
        if not keep_article(art):
            continue
        seen_title.add(title_key)
        kept.append(art)
    return kept
