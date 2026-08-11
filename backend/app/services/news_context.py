"""
Lightweight market news bias via Grok (xAI) when GROK_API_KEY is set.

Used as an optional confluence input — never the sole trade trigger.
Falls back to a neutral stub when the key is missing or the call fails.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import pytz

from app.core.config import get_settings

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")

CACHE_TTL_SECS = 900  # 15 minutes success
FAIL_CACHE_SECS = 300  # 5 minutes after hard failures

# Prefer newer models first; fall back if model not found / forbidden
DEFAULT_MODEL_CANDIDATES = [
    "grok-3-mini",
    "grok-3-mini-fast",
    "grok-2-1212",
    "grok-2-latest",
    "grok-beta",
]


class NewsContextService:
    def __init__(self):
        self._cache: Optional[Dict[str, Any]] = None
        self._cached_at: float = 0.0
        self._cache_ttl: float = CACHE_TTL_SECS
        self._last_model: Optional[str] = None

    def get_market_bias(self, force: bool = False) -> Dict[str, Any]:
        now = time.time()
        if (
            not force
            and self._cache is not None
            and (now - self._cached_at) < self._cache_ttl
        ):
            return {**self._cache, "cached": True}

        settings = get_settings()
        if not (settings.grok_api_key or "").strip():
            result = {
                "success": True,
                "available": False,
                "bias": "NEUTRAL",
                "score": 50,
                "summary": "Grok news not configured (set GROK_API_KEY in backend/.env)",
                "headlines": [],
                "model": None,
                "timestamp": datetime.now(IST).isoformat(),
            }
            self._store(result, CACHE_TTL_SECS)
            return result

        try:
            result = self._call_grok_with_fallback(settings)
            self._store(result, CACHE_TTL_SECS)
            return result
        except Exception as exc:
            logger.warning(f"[NewsContext] Grok call failed: {exc}")
            hard = any(x in str(exc).lower() for x in ("401", "403", "unauthorized", "forbidden", "invalid api"))
            result = {
                "success": False,
                "available": not hard,  # key present but failed; hard auth → treat as unavailable
                "bias": "NEUTRAL",
                "score": 50,
                "summary": f"News fetch failed: {exc}",
                "headlines": [],
                "model": self._last_model,
                "timestamp": datetime.now(IST).isoformat(),
            }
            self._store(result, FAIL_CACHE_SECS if hard else 120)
            return result

    def _store(self, result: Dict[str, Any], ttl: float) -> None:
        self._cache = result
        self._cached_at = time.time()
        self._cache_ttl = ttl

    def _model_candidates(self, settings) -> List[str]:
        preferred = getattr(settings, "grok_model", None) or ""
        preferred = preferred.strip()
        models: List[str] = []
        if preferred:
            models.append(preferred)
        for m in DEFAULT_MODEL_CANDIDATES:
            if m not in models:
                models.append(m)
        return models

    def _call_grok_with_fallback(self, settings) -> Dict[str, Any]:
        last_err: Optional[Exception] = None
        for model in self._model_candidates(settings):
            try:
                return self._call_grok(settings, model)
            except httpx.HTTPStatusError as exc:
                last_err = exc
                code = exc.response.status_code
                body = ""
                try:
                    body = exc.response.text[:300]
                except Exception:
                    pass
                # Model not found / not allowed → try next
                if code in (400, 404) and any(
                    t in body.lower()
                    for t in ("model", "not found", "does not exist", "invalid")
                ):
                    logger.info(f"[NewsContext] model {model} rejected ({code}), trying next")
                    continue
                if code in (401, 403):
                    raise RuntimeError(
                        f"Grok auth failed ({code}). Check GROK_API_KEY permissions."
                    ) from exc
                # Other errors: try next model once, then raise
                logger.info(f"[NewsContext] model {model} HTTP {code}: {body[:120]}")
                continue
            except Exception as exc:
                last_err = exc
                logger.info(f"[NewsContext] model {model} error: {exc}")
                continue
        raise RuntimeError(str(last_err) if last_err else "All Grok models failed")

    def _call_grok(self, settings, model: str) -> Dict[str, Any]:
        url = f"{settings.grok_api_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.grok_api_key}",
            "Content-Type": "application/json",
        }
        prompt = (
            "You are a market news analyst for Indian NSE F&O traders. "
            "Summarize the current macro / India equity / global risk tone in 3 short bullets. "
            "Then output exactly one line: BIAS: BULLISH|BEARISH|NEUTRAL and SCORE: 0-100 "
            "where 100=very bullish risk-on. Keep total under 120 words."
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Be concise. No trading advice disclaimer fluff."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 300,
        }

        with httpx.Client(timeout=25.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        self._last_model = model

        text = ""
        try:
            text = data["choices"][0]["message"]["content"]
        except Exception:
            text = str(data)[:500]

        bias = "NEUTRAL"
        score = 50
        upper = text.upper()
        if "BIAS: BULLISH" in upper or "BIAS:BULLISH" in upper:
            bias = "BULLISH"
        elif "BIAS: BEARISH" in upper or "BIAS:BEARISH" in upper:
            bias = "BEARISH"

        m = re.search(r"SCORE:\s*(\d{1,3})", upper)
        if m:
            score = max(0, min(100, int(m.group(1))))
        elif bias == "BULLISH":
            score = 65
        elif bias == "BEARISH":
            score = 35

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        headlines = [
            ln.lstrip("•- ").strip()
            for ln in lines
            if not ln.upper().startswith("BIAS") and not ln.upper().startswith("SCORE")
        ][:5]

        return {
            "success": True,
            "available": True,
            "bias": bias,
            "score": score,
            "summary": text[:600],
            "headlines": headlines,
            "model": model,
            "timestamp": datetime.now(IST).isoformat(),
            "cached": False,
        }


_news: Optional[NewsContextService] = None


def get_news_service() -> NewsContextService:
    global _news
    if _news is None:
        _news = NewsContextService()
    return _news
