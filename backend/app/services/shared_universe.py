"""
Shared hot-symbol pool across strategies.

Other modules already pay Fyers cost (HV scan, radar, MA rotation, stock quant jobs).
MA 7/200 and similar filters should prefer these symbols + cached history
instead of re-hitting the full F&O universe.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


def _add(out: Set[str], sources: Dict[str, int], symbol: Optional[str], source: str) -> None:
    if not symbol or not isinstance(symbol, str):
        return
    if not symbol.startswith("NSE:"):
        return
    # Prefer equity symbols for stock option strategies
    if "-EQ" not in symbol and "INDEX" in symbol.upper():
        return
    out.add(symbol)
    sources[source] = sources.get(source, 0) + 1


def collect_shared_strategy_symbols(limit: int = 80) -> Dict[str, Any]:
    """
    Gather symbols already touched by other strategies (newest/most useful first).
    """
    from app.services.fno_stocks import filter_valid_symbols, TOP_FNO_STOCKS

    ordered: List[str] = []
    seen: Set[str] = set()
    sources: Dict[str, int] = {}

    def push(sym: str, source: str) -> None:
        if sym in seen:
            return
        tmp: Set[str] = set()
        _add(tmp, sources, sym, source)
        if not tmp:
            return
        s = next(iter(tmp))
        seen.add(s)
        ordered.append(s)

    # 1) High-volume scanner last results
    try:
        from app.services.high_volume_scanner import get_scanner_service
        hv = get_scanner_service().get_last_scan(max_age_seconds=3600)
        if hv:
            for row in (hv.get("top_stocks") or []) + (hv.get("all_high_volume") or []):
                push(row.get("symbol") or "", "high_volume")
    except Exception as e:
        logger.debug("[shared_universe] hv: %s", e)

    # 2) Radar last scan / cache (flagged only — not full 180 watchlist)
    try:
        from app.services.option_flow_radar import get_radar_service
        radar = get_radar_service()
        last = radar.get_last_scan() or radar.get_cached_scan(max_age_seconds=3600) or {}
        for row in (last.get("flagged") or [])[:40]:
            push(row.get("symbol") or "", "radar")
        # Small slice of default watch as warm targets only
        wl = radar.get_watchlist() or []
        for w in wl[:20]:
            if isinstance(w, dict):
                push(w.get("symbol") or "", "radar_watch")
            elif isinstance(w, str):
                push(w, "radar_watch")
    except Exception as e:
        logger.debug("[shared_universe] radar: %s", e)

    # 3) MA crossover service (active crosses + last scan chunk)
    try:
        from app.services.strategies.ma_crossover import get_ma_crossover_service
        ma = get_ma_crossover_service()
        for row in (ma.get_crossovers() or [])[:40]:
            push(row.get("symbol") or "", "ma_crossover")
        for row in (ma.get_nearing() or [])[:20]:
            push(row.get("symbol") or "", "ma_nearing")
        chunk = getattr(ma, "_last_scan_chunk", None) or []
        for sym in chunk[:40]:
            push(sym, "ma_scan_chunk")
    except Exception as e:
        logger.debug("[shared_universe] ma: %s", e)

    # 4) Stock quant scan jobs (completed results)
    try:
        from app.services.scan_jobs import get_scan_job_manager
        mgr = get_scan_job_manager()
        for job_meta in mgr.list_jobs(kind="stocks_scan", limit=3):
            jid = job_meta.get("id")
            if not jid:
                continue
            snap = mgr.snapshot(jid, include_results=True) or {}
            for row in snap.get("results") or []:
                push(row.get("symbol") or "", "stocks_scan")
    except Exception as e:
        logger.debug("[shared_universe] jobs: %s", e)

    # 5) Tech filter local cache keys (symbols already history-warmed)
    try:
        from app.services import tech_filters as tf
        with tf._local_lock:
            for k in list(tf._local_cache.keys())[:50]:
                if k.startswith("tech:"):
                    push(k.replace("tech:", "", 1), "tech_cache")
    except Exception as e:
        logger.debug("[shared_universe] tech: %s", e)

    # 6) Small liquid fallback so UI is never empty of a pool
    for sym in TOP_FNO_STOCKS[:25]:
        push(sym, "top_fno_fallback")

    filtered = filter_valid_symbols(ordered)[:limit]
    return {
        "symbols": filtered,
        "count": len(filtered),
        "sources": sources,
        "note": "Symbols already used by HV / Radar / MA / Stocks scan — filter only",
    }
