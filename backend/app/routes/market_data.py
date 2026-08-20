from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional, List
from pydantic import BaseModel

from app.services.fyers_market import get_market_service
from app.services.fno_intelligence import get_intelligence_engine
from app.services.fno_stocks import get_fno_stocks, TOP_FNO_STOCKS
from app.services.high_volume_scanner import get_scanner_service

router = APIRouter()
market_service = get_market_service()
intelligence_engine = get_intelligence_engine()
scanner_service = get_scanner_service()


class BulkAnalysisRequest(BaseModel):
    """Request model for bulk option chain analysis"""
    symbols: List[str]


class StartStockScanBody(BaseModel):
    """Optional body for background stock scan start / retry list."""
    symbols: Optional[List[str]] = None


@router.get("/market/spot/{symbol}")
async def get_spot_price(symbol: str):
    """Get current spot price for a symbol."""
    import asyncio
    result = await asyncio.to_thread(market_service.get_spot_price, symbol)
    if result.get("success"):
        return result
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to fetch spot price"))


@router.get("/market/state")
async def get_market_state(symbol: str = Query("NSE:NIFTY50-INDEX", description="Symbol to analyze")):
    """
    Get market state analysis using the F&O Intelligence Engine.
    
    Returns:
        Market state classification (TREND, RANGE, INTENT, ADJUSTMENT, NO-TRADE),
        confidence level, analysis details, and trading signals.
    """
    import asyncio
    from app.services.signal_bus import get_signal_bus

    # Offload blocking Fyers + analysis off the event loop
    from app.services.symbol_store import canonical_strike_count

    chain_data = await asyncio.to_thread(
        market_service.get_option_chain, symbol, canonical_strike_count(symbol)
    )
    
    if not chain_data.get("success"):
        raise HTTPException(status_code=400, detail=chain_data.get("error", "Failed to fetch option chain"))
    
    analysis = await asyncio.to_thread(intelligence_engine.get_analysis_summary, chain_data)

    # Only publish high-confidence actionable setups (not every PCR/VIX blurb).
    # Signal bus already dedupes; keep this tight so 45s UI polls don't spam.
    try:
        bus = get_signal_bus()
        adj = analysis.get("adjustment") or {}
        conf = float(adj.get("confidence") or analysis.get("confidence") or 0)
        if (
            adj.get("detected")
            and adj.get("trade_setup")
            and conf >= 60
            and analysis.get("tradable")
        ):
            setup = adj["trade_setup"]
            bus.publish(
                source="intelligence",
                message=f"{setup.get('action')} on {symbol}: {setup.get('rationale', '')}",
                level="signal",
                symbol=symbol,
                score=conf,
                meta={"state": analysis.get("state"), "strikes": setup.get("strikes")},
            )
    except Exception:
        pass
    
    return analysis


def _resolve_stock_universe(limit: int, top_only: bool) -> list:
    from app.services.fno_stocks import filter_valid_symbols, get_fno_stocks as _all_fno

    if top_only:
        return filter_valid_symbols(list(TOP_FNO_STOCKS))[:limit]
    return filter_valid_symbols(list(_all_fno(top_only=False)))[:limit]


def _apply_setup_side(analysis: dict) -> dict:
    """
    Column lean (BULLISH/BEARISH) is separate from trade ACTION (WAIT/BUY/SELL).

    WAIT + Long Buildup still appears under Bullish as a watch — so the UI is not
    empty when the market is conflicted. Action badge stays WAIT.
    """
    lean = (
        analysis.get("lean_bias")
        or analysis.get("quant_bias")
        or analysis.get("buildup_bias")
        or (analysis.get("buildup") or {}).get("bias")
        or "NEUTRAL"
    )
    # Buildup primary can force lean even if quant was flattened
    b_state = analysis.get("buildup_state") or (analysis.get("buildup") or {}).get(
        "primary_state"
    )
    if lean not in ("BULLISH", "BEARISH"):
        if b_state == "Long Buildup" or analysis.get("watch_long"):
            lean = "BULLISH"
        elif b_state in ("Short Buildup",) or analysis.get("watch_short"):
            lean = "BEARISH"
        elif b_state == "Long Unwinding" and (
            analysis.get("buildup_bias") == "BEARISH"
        ):
            lean = "BEARISH"

    if lean in ("BULLISH", "BEARISH"):
        analysis["setup_side"] = lean
    else:
        g_bias = (analysis.get("strike_guidance") or {}).get("bias") or "NEUTRAL"
        analysis["setup_side"] = g_bias if g_bias in ("BULLISH", "BEARISH") else "NEUTRAL"

    # Never suggest directional trades when action is WAIT
    action = analysis.get("action") or ""
    if action == "WAIT" and analysis.get("strike_guidance"):
        sg = dict(analysis["strike_guidance"])
        if sg.get("suggested") and not analysis.get("entry_long") and not analysis.get(
            "entry_short"
        ):
            sg["suggested"] = False
            sg["expert_note"] = (
                sg.get("expert_note")
                or analysis.get("verdict")
                or "Watch only — no entry while action is WAIT"
            )
            analysis["strike_guidance"] = sg
    elif analysis.get("strike_guidance") and analysis["setup_side"] != "NEUTRAL":
        sg = dict(analysis["strike_guidance"])
        if sg.get("bias") != analysis["setup_side"] and sg.get("suggested"):
            sg["bias"] = analysis["setup_side"]
        analysis["strike_guidance"] = sg
    return analysis


def _summarize_stock_results(
    results: list,
    errors: list,
    stocks: list,
    *,
    top_only: bool,
    strike_count: int,
    deep: bool,
    skipped_rate_limit: int,
    tradable_only: bool,
    job_id: str | None = None,
) -> dict:
    from datetime import datetime

    out = list(results)
    if tradable_only:
        out = [r for r in out if r.get("tradable")]

    out.sort(
        key=lambda x: (
            -(x.get("quant_score") or x.get("confidence") or 0),
            -(x.get("intent_score") or 0),
            x.get("symbol") or "",
        )
    )
    bull_n = sum(1 for r in out if r.get("setup_side") == "BULLISH")
    bear_n = sum(1 for r in out if r.get("setup_side") == "BEARISH")
    neut_n = sum(1 for r in out if r.get("setup_side") == "NEUTRAL")

    payload = {
        "success": True,
        "count": len(out),
        "total_scanned": len(results) + len(errors),
        "completed": len(results),
        "tradable_count": sum(1 for r in out if r.get("tradable")),
        "universe_requested": len(stocks),
        "completion_pct": round(100.0 * len(results) / max(len(stocks), 1), 1),
        "bullish_count": bull_n,
        "bearish_count": bear_n,
        "neutral_count": neut_n,
        "top_only": top_only,
        "strike_count": strike_count,
        "deep": deep,
        "stocks": out,
        "errors": errors if errors else None,
        "error_count": len(errors),
        "rate_limited_skips": skipped_rate_limit,
        "partial": len(results) < len(stocks),
        "timestamp": datetime.now().isoformat(),
    }
    if job_id:
        payload["job_id"] = job_id
    return payload


async def _analyze_one_stock(symbol: str, strike_count: int, deep: bool) -> dict:
    """Analyze a single symbol from the harvest store (CPU). No Fyers walk."""
    import asyncio
    from app.services import symbol_store as store

    try:
        chain_data = store.get_chain(symbol, strike_count)
        if not chain_data or not chain_data.get("success"):
            return {"symbol": symbol, "error": "chain not harvested yet"}

        analysis = await asyncio.to_thread(
            intelligence_engine.analyze_stock, symbol, chain_data
        )
        if "error" in analysis:
            return {"symbol": symbol, "error": analysis.get("error")}
        analysis["symbol"] = analysis.get("symbol") or symbol
        analysis = _apply_setup_side(analysis)
        if not deep:
            analysis.pop("deep_analytics", None)
        return {"ok": True, "data": analysis}
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}


async def _run_stock_scan_batches(
    stocks: list,
    strike_count: int,
    deep: bool,
    *,
    job_id: str | None = None,
    seed_results: list | None = None,
    seed_errors: list | None = None,
) -> tuple[list, list, int]:
    """
    Process symbols in rate-limited batches.
    Optionally streams progress into ScanJobManager when job_id is set.
    """
    import asyncio
    from app.services.rate_limiter import get_fyers_limiter
    from app.services.scan_jobs import get_scan_job_manager

    results: list = list(seed_results or [])
    errors: list = list(seed_errors or [])
    skipped_rate_limit = 0
    limiter = get_fyers_limiter()
    mgr = get_scan_job_manager() if job_id else None
    BATCH = 3

    for i in range(0, len(stocks), BATCH):
        if limiter.in_cooldown and i > 0:
            wait = min(limiter.cooldown_remaining, 45.0)
            if wait > 0:
                if mgr and job_id:
                    mgr.set_current(job_id, f"cooldown {wait:.0f}s")
                await asyncio.sleep(wait)
        batch = stocks[i : i + BATCH]
        if mgr and job_id and batch:
            mgr.set_current(job_id, batch[0])
        outcomes = await asyncio.gather(
            *[_analyze_one_stock(s, strike_count, deep) for s in batch]
        )
        for out in outcomes:
            if out.get("ok"):
                results.append(out["data"])
                if mgr and job_id:
                    mgr.append_result(job_id, out["data"])
            else:
                sym = out.get("symbol") or "?"
                err = out.get("error") or "unknown"
                rl = bool(out.get("rate_limited"))
                if rl:
                    skipped_rate_limit += 1
                errors.append({"symbol": sym, "error": err, "rate_limited": rl})
                if mgr and job_id:
                    mgr.append_error(job_id, sym, err, rate_limited=rl)

    return results, errors, skipped_rate_limit


@router.get("/market/stocks/scan")
async def scan_fno_stocks(
    limit: int = Query(200, ge=1, le=250, description="Max stocks to analyze (full F&O)"),
    tradable_only: bool = Query(False, description="Only return tradable states"),
    top_only: bool = Query(False, description="If true, only TOP liquid F&O names"),
    strike_count: int = Query(14, ge=5, le=20, description="Strikes above/below ATM"),
    deep: bool = Query(True, description="Include deep mathematical analytics"),
):
    """
    Deep-scan F&O stocks with option-chain mathematics (blocking HTTP).

    Prefer POST /market/stocks/scan/start + GET .../jobs/{id} for full-universe
    scans so the UI can show live progress.
    """
    stocks = _resolve_stock_universe(limit, top_only)
    results, errors, skipped_rate_limit = await _run_stock_scan_batches(
        stocks, strike_count, deep
    )
    return _summarize_stock_results(
        results,
        errors,
        stocks,
        top_only=top_only,
        strike_count=strike_count,
        deep=deep,
        skipped_rate_limit=skipped_rate_limit,
        tradable_only=tradable_only,
    )


def _merge_stock_rows(base: list, updates: list) -> list:
    """Merge by symbol: updates win; keep base rows not in updates."""
    by_sym: dict = {}
    for row in base or []:
        sym = row.get("symbol")
        if sym:
            by_sym[sym] = row
    for row in updates or []:
        sym = row.get("symbol")
        if sym:
            by_sym[sym] = row
    merged = list(by_sym.values())
    merged.sort(
        key=lambda x: (
            -(x.get("quant_score") or x.get("confidence") or 0),
            -(x.get("intent_score") or 0),
            x.get("symbol") or "",
        )
    )
    return merged


async def _start_stock_scan_internal(
    *,
    limit: int,
    tradable_only: bool,
    top_only: bool,
    strike_count: int,
    deep: bool,
    symbols: Optional[List[str]] = None,
    merge_from_job_id: Optional[str] = None,
    universe_size: Optional[int] = None,
) -> dict:
    """Shared worker launcher for HTTP start + retry-failed (optional merge)."""
    import asyncio
    from app.services.fno_stocks import filter_valid_symbols
    from app.services.scan_jobs import get_scan_job_manager

    if symbols:
        stocks = filter_valid_symbols(list(symbols))[:limit]
    else:
        stocks = _resolve_stock_universe(limit, top_only)

    mgr = get_scan_job_manager()
    base_rows: list = []
    base_universe = universe_size
    if merge_from_job_id:
        prev = mgr.get(merge_from_job_id)
        if prev:
            # Prefer finished summary stocks, else live results
            prev_summary = (prev.meta or {}).get("summary") or {}
            base_rows = list(prev_summary.get("stocks") or prev.results or [])
            if base_universe is None:
                base_universe = (
                    prev_summary.get("universe_requested")
                    or prev.total
                    or len(base_rows)
                )

    job = mgr.create(
        kind="stocks_scan",
        total=len(stocks),
        label=(
            f"retry+merge {len(stocks)} failed"
            if merge_from_job_id
            else (
                f"retry {len(stocks)} failed"
                if symbols
                else ("full F&O quant" if not top_only else "top liquid F&O")
            )
        ),
        meta={
            "limit": limit,
            "top_only": top_only,
            "tradable_only": tradable_only,
            "strike_count": strike_count,
            "deep": deep,
            "custom_symbols": bool(symbols),
            "merge_from_job_id": merge_from_job_id,
            "base_count": len(base_rows),
            "universe_size": base_universe,
        },
        pending_symbols=list(stocks),
    )
    # Seed UI with previous successes immediately
    if base_rows:
        mgr.set_results(job.id, list(base_rows))
        mgr.update(job.id, completed=0)
    mgr.mark_running(job.id)

    async def _worker():
        try:
            results, errors, skipped = await _run_stock_scan_batches(
                stocks, strike_count, deep, job_id=job.id
            )
            # Local `results` are only the symbols scanned this run;
            # merge with previous successes for a growing grid.
            new_only = list(results)
            merged = _merge_stock_rows(base_rows, new_only) if base_rows else new_only

            summary = _summarize_stock_results(
                merged,
                errors,
                stocks,
                top_only=top_only,
                strike_count=strike_count,
                deep=deep,
                skipped_rate_limit=skipped,
                tradable_only=tradable_only,
                job_id=job.id,
            )
            if base_rows:
                # Fix universe / partial against original full universe
                u = int(base_universe or max(len(base_rows) + len(stocks), len(merged)))
                summary["universe_requested"] = u
                summary["completed"] = len(merged)
                summary["count"] = len(summary["stocks"])
                summary["completion_pct"] = round(
                    100.0 * len(merged) / max(u, 1), 1
                )
                summary["partial"] = len(merged) < u
                summary["merged_from"] = merge_from_job_id
                summary["retry_new_count"] = len(new_only)
                summary["bullish_count"] = sum(
                    1 for r in summary["stocks"] if r.get("setup_side") == "BULLISH"
                )
                summary["bearish_count"] = sum(
                    1 for r in summary["stocks"] if r.get("setup_side") == "BEARISH"
                )
                summary["neutral_count"] = sum(
                    1 for r in summary["stocks"] if r.get("setup_side") == "NEUTRAL"
                )
                summary["tradable_count"] = sum(
                    1 for r in summary["stocks"] if r.get("tradable")
                )

            compact = {
                k: summary[k]
                for k in (
                    "count",
                    "completed",
                    "tradable_count",
                    "universe_requested",
                    "completion_pct",
                    "bullish_count",
                    "bearish_count",
                    "neutral_count",
                    "partial",
                    "rate_limited_skips",
                    "error_count",
                    "timestamp",
                )
                if k in summary
            }
            if base_rows:
                compact["merged_from"] = merge_from_job_id
                compact["retry_new_count"] = len(new_only)
            mgr.update(job.id, results=summary["stocks"])
            mgr.finish(
                job.id,
                status="completed",
                extra_meta={"summary": {**compact, "stocks": summary["stocks"]}},
            )
        except asyncio.CancelledError:
            mgr.finish(job.id, status="cancelled", error_message="cancelled")
            raise
        except Exception as e:
            mgr.finish(job.id, status="failed", error_message=str(e))

    task = asyncio.create_task(_worker())
    mgr.register_task(job.id, task)

    return {
        "success": True,
        "job_id": job.id,
        "status": "running",
        "total": len(stocks),
        "label": job.label,
        "merge_from_job_id": merge_from_job_id,
        "base_count": len(base_rows),
        "poll_url": f"/api/v1/market/stocks/scan/jobs/{job.id}",
    }


@router.post("/market/stocks/scan/start")
async def start_stock_scan_job(
    limit: int = Query(200, ge=1, le=250),
    tradable_only: bool = Query(False),
    top_only: bool = Query(False),
    strike_count: int = Query(14, ge=5, le=20),
    deep: bool = Query(True),
    body: Optional[StartStockScanBody] = Body(default=None),
):
    """
    Start a background F&O quant scan. Poll GET /market/stocks/scan/jobs/{job_id}.
    Optionally pass {\"symbols\": [...]} to scan/retry a custom list only.
    """
    return await _start_stock_scan_internal(
        limit=limit,
        tradable_only=tradable_only,
        top_only=top_only,
        strike_count=strike_count,
        deep=deep,
        symbols=(body.symbols if body else None),
    )


@router.get("/market/stocks/scan/jobs/{job_id}")
async def get_stock_scan_job(
    job_id: str,
    include_results: bool = Query(True, description="Include full stock rows (large)"),
):
    """Poll background stock scan progress + results."""
    from app.services.scan_jobs import get_scan_job_manager

    mgr = get_scan_job_manager()
    snap = mgr.snapshot(job_id, include_results=include_results)
    if not snap:
        raise HTTPException(status_code=404, detail="Job not found (expired or invalid id)")

    # Shape a ScanResponse-compatible payload for the UI when finished/running
    meta = snap.get("meta") or {}
    summary = meta.get("summary") or {}
    stocks = snap.get("results") or []
    if summary and isinstance(summary, dict) and "stocks" in summary:
        # full summary stored on finish
        stocks = summary.get("stocks") or stocks

    # Prefer finished summary metrics (esp. after merge-retry) over raw job counters
    universe = summary.get("universe_requested", snap["total"])
    completed = summary.get("completed", snap["completed"])
    completion_pct = summary.get(
        "completion_pct", snap.get("completion_pct", 0)
    )
    partial = summary.get("partial")
    if partial is None:
        partial = snap.get("partial") or False

    return {
        "success": True,
        "job_id": job_id,
        "status": snap["status"],
        "label": snap.get("label"),
        "total": snap["total"],
        "completed": completed,
        "failed": snap["failed"],
        "rate_limited_skips": summary.get(
            "rate_limited_skips", snap.get("rate_limited_skips", 0)
        ),
        "current_symbol": snap.get("current_symbol"),
        "completion_pct": completion_pct,
        "partial": partial,
        "error_message": snap.get("error_message"),
        "created_at": snap.get("created_at"),
        "started_at": snap.get("started_at"),
        "finished_at": snap.get("finished_at"),
        "failed_symbols": snap.get("failed_symbols") or [],
        "merged_from": summary.get("merged_from"),
        "retry_new_count": summary.get("retry_new_count"),
        # ScanResponse fields (for drop-in UI use when status=completed)
        "count": summary.get("count", len(stocks)),
        "total_scanned": summary.get(
            "total_scanned", snap["completed"] + snap["failed"]
        ),
        "tradable_count": summary.get(
            "tradable_count", sum(1 for r in stocks if r.get("tradable"))
        ),
        "universe_requested": universe,
        "bullish_count": summary.get(
            "bullish_count",
            sum(1 for r in stocks if r.get("setup_side") == "BULLISH"),
        ),
        "bearish_count": summary.get(
            "bearish_count",
            sum(1 for r in stocks if r.get("setup_side") == "BEARISH"),
        ),
        "neutral_count": summary.get(
            "neutral_count",
            sum(1 for r in stocks if r.get("setup_side") == "NEUTRAL"),
        ),
        "stocks": stocks if include_results else [],
        "errors": snap.get("errors"),
        "error_count": summary.get("error_count", snap.get("error_count", 0)),
        "timestamp": summary.get("timestamp") or snap.get("finished_at") or snap.get("created_at"),
    }


@router.post("/market/stocks/scan/jobs/{job_id}/retry-failed")
async def retry_failed_stock_scan(job_id: str):
    """
    Re-scan only failed / rate-limited symbols and **merge** into previous
    successful rows so the grid grows instead of replacing with a tiny set.
    """
    from app.services.scan_jobs import get_scan_job_manager

    mgr = get_scan_job_manager()
    prev = mgr.get(job_id)
    if not prev:
        raise HTTPException(status_code=404, detail="Job not found")
    failed = list(prev.failed_symbols)
    if not failed:
        return {
            "success": True,
            "message": "No failed symbols to retry",
            "job_id": None,
            "failed_count": 0,
        }
    meta = dict(prev.meta or {})
    prev_summary = (prev.meta or {}).get("summary") or {}
    universe = (
        prev_summary.get("universe_requested")
        or meta.get("universe_size")
        or prev.total
    )
    started = await _start_stock_scan_internal(
        limit=len(failed),
        tradable_only=bool(meta.get("tradable_only", False)),
        top_only=bool(meta.get("top_only", False)),
        strike_count=int(meta.get("strike_count", 10)),
        deep=bool(meta.get("deep", True)),
        symbols=failed,
        merge_from_job_id=job_id,
        universe_size=int(universe) if universe else None,
    )
    started["failed_count"] = len(failed)
    started["merged"] = True
    return started


@router.get("/market/stocks/scan/jobs")
async def list_stock_scan_jobs(limit: int = Query(10, ge=1, le=50)):
    """List recent stock scan jobs (no full result payloads)."""
    from app.services.scan_jobs import get_scan_job_manager

    mgr = get_scan_job_manager()
    return {"success": True, "jobs": mgr.list_jobs(kind="stocks_scan", limit=limit)}


@router.get("/market/cache-stats")
async def market_cache_stats():
    """Debug: short-TTL market data cache hit rates + Redis + scan jobs."""
    from app.services.market_cache import get_market_cache
    from app.services.rate_limiter import get_fyers_limiter
    from app.services.redis_client import status as redis_status
    from app.services.scan_jobs import get_scan_job_manager

    lim = get_fyers_limiter()
    return {
        "success": True,
        "cache": get_market_cache().stats(),
        "redis": redis_status(),
        "scan_jobs": get_scan_job_manager().stats(),
        "rate_limit": {
            "in_cooldown": lim.in_cooldown,
            "cooldown_remaining": round(lim.cooldown_remaining, 1),
        },
    }


@router.get("/market/store/status")
async def get_store_status():
    """Harvest / Redis symbol-store health for the UI book banner."""
    from app.services.symbol_store import status as store_status
    from app.services.redis_client import status as redis_status

    st = store_status()
    st["redis_detail"] = redis_status()
    return {"success": True, **st}


@router.get("/market/indices")
async def get_indices():
    """Get major market indices data."""
    import asyncio
    result = await asyncio.to_thread(market_service.get_indices)
    if result.get("success"):
        return result
    else:
        # Return graceful degradation
        return {"success": False, "data": [], "error": result.get("error")}


@router.get("/market/history/{symbol}")
async def get_history(
    symbol: str,
    resolution: str = "D",
    days: int = 30
):
    """Get historical OHLCV data."""
    import asyncio
    result = await asyncio.to_thread(
        market_service.get_historical_data, symbol, resolution, None, None, days
    )
    if result.get("success"):
        return result
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to fetch history"))


@router.get("/market/high-volume-scan")
async def scan_high_volume_stocks(
    timeframe: str = Query("15", description="Timeframe in minutes: 15 or 60"),
    top_count: int = Query(5, ge=1, le=20, description="Number of top stocks to return")
):
    """
    Blocking high-volume scan (legacy). Prefer POST /market/high-volume-scan/start.
    """
    try:
        result = await scanner_service.scan_high_volume_stocks(
            timeframe=timeframe,
            top_count=top_count
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")


@router.post("/market/high-volume-scan/start")
async def start_high_volume_scan_job(
    timeframe: str = Query("15", description="15 or 60"),
    top_count: int = Query(5, ge=1, le=20),
):
    """Start background HV scan. Poll GET /market/high-volume-scan/jobs/{job_id}."""
    import asyncio
    from app.services.fno_stocks import FNO_STOCKS
    from app.services.scan_jobs import get_scan_job_manager

    total = len(FNO_STOCKS)
    mgr = get_scan_job_manager()
    job = mgr.create(
        kind="high_volume",
        total=total,
        label=f"high volume {timeframe}m",
        meta={"timeframe": timeframe, "top_count": top_count},
        pending_symbols=list(FNO_STOCKS),
    )
    mgr.mark_running(job.id)

    def _progress(scanned: int, total_stocks: int):
        # high_volume_scanner callback is (scanned, total) only
        try:
            sym = FNO_STOCKS[min(scanned - 1, total_stocks - 1)] if scanned else None
        except Exception:
            sym = None
        mgr.set_current(job.id, sym)
        mgr.update(
            job.id,
            completed=scanned,
            completion_pct=round(100.0 * scanned / max(total_stocks, 1), 1),
        )

    async def _worker():
        try:
            result = await scanner_service.scan_high_volume_stocks(
                timeframe=timeframe,
                top_count=top_count,
                progress_callback=_progress,
            )
            top = result.get("top_stocks") or []
            mgr.set_results(job.id, top)
            mgr.update(
                job.id,
                completed=int(result.get("total_scanned") or total),
                completion_pct=100.0,
            )
            mgr.finish(
                job.id,
                status="completed",
                extra_meta={
                    "summary": {
                        "timeframe": result.get("timeframe"),
                        "total_scanned": result.get("total_scanned"),
                        "high_volume_count": result.get("high_volume_count"),
                        "top_stocks": top,
                        "all_high_volume": result.get("all_high_volume"),
                        "errors_count": result.get("errors_count"),
                        "errors": result.get("errors"),
                        "timestamp": result.get("timestamp"),
                        "partial": False,
                        "completion_pct": 100.0,
                    }
                },
            )
        except asyncio.CancelledError:
            mgr.finish(job.id, status="cancelled", error_message="cancelled")
            raise
        except Exception as e:
            mgr.finish(job.id, status="failed", error_message=str(e))

    task = asyncio.create_task(_worker())
    mgr.register_task(job.id, task)
    return {
        "success": True,
        "job_id": job.id,
        "status": "running",
        "total": total,
        "poll_url": f"/api/v1/market/high-volume-scan/jobs/{job.id}",
    }


@router.get("/market/high-volume-scan/jobs/{job_id}")
async def get_high_volume_scan_job(job_id: str):
    """Poll HV scan job progress + top stocks."""
    from app.services.scan_jobs import get_scan_job_manager

    mgr = get_scan_job_manager()
    snap = mgr.snapshot(job_id, include_results=True)
    if not snap:
        raise HTTPException(status_code=404, detail="Job not found")
    summary = (snap.get("meta") or {}).get("summary") or {}
    top = summary.get("top_stocks") or snap.get("results") or []
    return {
        "success": True,
        "job_id": job_id,
        "status": snap["status"],
        "total": snap["total"],
        "completed": snap["completed"],
        "current_symbol": snap.get("current_symbol"),
        "completion_pct": snap.get("completion_pct") or summary.get("completion_pct") or 0,
        "partial": snap.get("partial") or summary.get("partial", False),
        "error_message": snap.get("error_message"),
        "timeframe": summary.get("timeframe"),
        "total_scanned": summary.get("total_scanned", snap["completed"]),
        "high_volume_count": summary.get("high_volume_count", 0),
        "top_stocks": top,
        "all_high_volume": summary.get("all_high_volume"),
        "errors_count": summary.get("errors_count"),
        "errors": summary.get("errors"),
        "timestamp": summary.get("timestamp")
        or snap.get("finished_at")
        or snap.get("created_at"),
    }


@router.get("/market/fno-stocks")
async def get_fno_stocks_list():
    """
    Get list of all F&O stocks with cap classification.
    
    Returns:
        List of all FNO stocks with symbol, name, and cap (LARGE_CAP/MID_CAP)
    """
    try:
        stocks = scanner_service.get_all_fno_stocks()
        return {
            "success": True,
            "count": len(stocks),
            "stocks": stocks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/market/bulk-oc-analysis")
async def bulk_option_chain_analysis(
    request: BulkAnalysisRequest
):
    """
    Perform deep option chain analysis for multiple stocks.
    
    This endpoint analyzes:
    - OI concentrations (support/resistance levels)
    - Breakout signals (day high breaks, IV skew)
    - Greeks analysis (delta clustering, gamma concentration)
    - Market state from Intelligence Engine
    
    Args:
        symbols: List of stock symbols to analyze (e.g., ["NSE:RELIANCE-EQ", "NSE:TCS-EQ"])
        
    Returns:
        Ranked list of stocks with composite scores and detailed reasons
    """
    import asyncio
    
    if not request.symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")
    
    if len(request.symbols) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 symbols allowed per request")
    
    try:
        result = await scanner_service.bulk_option_chain_analysis(
            symbols=request.symbols
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/market/news-bias")
async def get_news_bias(force: bool = Query(False, description="Bypass cache and refresh from Grok")):
    """
    Optional Grok news/macro bias used by the confluence engine.
    Returns NEUTRAL when GROK_API_KEY is missing or the call fails.
    """
    import asyncio
    from app.services.news_context import get_news_service

    svc = get_news_service()
    return await asyncio.to_thread(svc.get_market_bias, force)


@router.get("/market/nifty-sentiment")
async def get_nifty_sentiment():
    """
    Get complete Nifty 50 sentiment dashboard data.
    
    Returns:
        VIX data, PCR analysis, market breadth, OI change, support/resistance levels
    """
    import asyncio
    from app.services.nifty_sentiment import get_sentiment_service
    
    sentiment_service = get_sentiment_service()
    return await asyncio.to_thread(sentiment_service.get_full_sentiment)


@router.get("/market/live-trade-signal/{symbol}")
async def get_live_trade_signal(symbol: str):
    """
    Get live trade signal for a specific symbol.
    
    Returns:
        Current trade recommendation with entry, stop-loss, target, and confidence
    """
    import asyncio
    try:
        # Fetch fresh option chain (cached + off event loop)
        from app.services.symbol_store import canonical_strike_count

        chain_data = await asyncio.to_thread(
            market_service.get_option_chain, symbol, canonical_strike_count(symbol)
        )
        
        if not chain_data.get("success"):
            raise HTTPException(status_code=400, detail=chain_data.get("error", "Failed to fetch OC"))
        
        spot_price = chain_data.get("spot_price") or 0
        atm_strike = chain_data.get("atm_strike") or 0
        
        if not spot_price or spot_price <= 0:
            raise HTTPException(status_code=400, detail="No valid spot price")
        
        # Perform analysis
        oi_analysis = scanner_service._analyze_oi_concentrations(chain_data, spot_price)
        greeks_analysis = scanner_service._calculate_greeks_score(chain_data)
        intel_analysis = intelligence_engine.get_analysis_summary(chain_data, bypass_time_check=True)
        
        # Generate trade recommendation
        trade_rec = scanner_service._generate_trade_recommendation(
            symbol, spot_price, atm_strike,
            oi_analysis, greeks_analysis, intel_analysis
        )

        process_idea = None
        try:
            from app.services.idea_book import get_idea_book

            process_idea = get_idea_book().get(symbol)
        except Exception:
            process_idea = None

        # Locked process trade overrides the flickering live-signal card
        if process_idea and process_idea.get("status") == "ACTIVE":
            ex = process_idea.get("execution") or {}
            inst = ex.get("instrument") or {}
            side = process_idea.get("side")
            opt = (
                process_idea.get("trade_opt_type")
                or inst.get("opt_type")
                or process_idea.get("opt_type")
                or ("CE" if side == "LONG" else "PE")
            )
            strike = (
                process_idea.get("trade_strike")
                or inst.get("strike")
                or process_idea.get("strike")
            )
            entry = (
                process_idea.get("entry")
                if process_idea.get("entry") is not None
                else ex.get("entry")
            )
            stop = (
                process_idea.get("stop")
                if process_idea.get("stop") is not None
                else ex.get("stop")
            )
            target = (
                process_idea.get("target")
                if process_idea.get("target") is not None
                else ex.get("target")
            )
            entry_label = process_idea.get("entry_label") or ex.get("entry_label")
            trade_rec = {
                "action": "ACTIONABLE",
                "bias": process_idea.get("direction"),
                "option_type": opt,
                "strike": strike,
                "confidence": "HIGH",
                "expert_note": process_idea.get("thesis"),
                "trades": [
                    {
                        "action": "BUY",
                        "type": "PROCESS",
                        "option_type": opt,
                        "strike": strike,
                        "entry_zone": (
                            f"{entry_label} {entry}"
                            if entry is not None
                            else f"spot {spot_price}"
                        ),
                        "stop_loss": stop,
                        "target": target,
                        "confidence": "HIGH",
                        "reason": process_idea.get("thesis"),
                    }
                ],
            }
        
        return {
            "symbol": symbol,
            "name": symbol.replace("NSE:", "").replace("-EQ", ""),
            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "oi_analysis": oi_analysis,
            "greeks_analysis": greeks_analysis,
            "intel_state": intel_analysis.get("state"),
            "tradable": bool(
                (process_idea and process_idea.get("status") == "ACTIVE")
                or intel_analysis.get("tradable")
            ),
            "trade_recommendation": trade_rec,
            "process_idea": process_idea,
            "timestamp": chain_data.get("timestamp")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/market/greeks-heatmap/{symbol}")
async def get_greeks_heatmap(
    symbol: str,
    strike_count: int = Query(14, ge=5, le=30, description="Number of strikes to include")
):
    """
    Get Greeks heatmap data for visualization.
    
    Returns:
        Strike-wise Delta, Gamma, Theta, Vega for both CE and PE
    """
    import asyncio
    chain_data = await asyncio.to_thread(
        market_service.get_option_chain, symbol, strike_count
    )
    
    if not chain_data.get("success"):
        raise HTTPException(status_code=400, detail=chain_data.get("error", "Failed to fetch OC"))
    
    spot_price = chain_data.get("spot_price") or 0
    atm_strike = chain_data.get("atm_strike") or 0
    chain = chain_data.get("chain", [])
    
    heatmap_data = []
    for strike_data in chain:
        strike = strike_data.get("strike_price", 0)
        call = strike_data.get("call", {}) or {}
        put = strike_data.get("put", {}) or {}
        
        heatmap_data.append({
            "strike": strike,
            "is_atm": strike == atm_strike,
            "is_itm_ce": strike < spot_price,
            "is_itm_pe": strike > spot_price,
            "call_delta": call.get("delta") or 0,
            "call_gamma": call.get("gamma") or 0,
            "call_theta": call.get("theta") or 0,
            "call_vega": call.get("vega") or 0,
            "call_iv": call.get("iv") or 0,
            "call_oi": call.get("oi") or 0,
            "call_ltp": call.get("ltp") or 0,
            "put_delta": put.get("delta") or 0,
            "put_gamma": put.get("gamma") or 0,
            "put_theta": put.get("theta") or 0,
            "put_vega": put.get("vega") or 0,
            "put_iv": put.get("iv") or 0,
            "put_oi": put.get("oi") or 0,
            "put_ltp": put.get("ltp") or 0
        })
    
    # Find max gamma strike (key pivot point)
    max_gamma_strike = max(heatmap_data, key=lambda x: abs(x["call_gamma"]) + abs(x["put_gamma"]), default=None)
    
    return {
        "symbol": symbol,
        "spot_price": spot_price,
        "atm_strike": atm_strike,
        "max_gamma_strike": max_gamma_strike.get("strike") if max_gamma_strike else None,
        "heatmap": heatmap_data,
        "timestamp": chain_data.get("timestamp")
    }
