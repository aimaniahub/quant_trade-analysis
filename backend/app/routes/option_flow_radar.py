"""
Option Flow Radar – FastAPI Routes
===================================
Exposes the OptionFlowRadar engine via REST endpoints consumed by the frontend.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from pydantic import BaseModel

from app.services.option_flow_radar import get_radar_service

router = APIRouter()


# ─────────────────────────────────────────────────────────────────
# Request bodies
# ─────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    symbol: str
    strike: int
    option_type: str
    signal_timestamp: str
    forward_minutes: List[int] = [15, 30, 60]


class ScanRequest(BaseModel):
    symbols: Optional[List[str]] = None
    min_lis: float = 0
    option_type: Optional[str] = None   # "CE" | "PE" | None
    strike_count: int = 14


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.get("/radar/watchlist")
async def get_watchlist():
    """
    Returns the default watchlist of symbols the radar monitors.
    """
    service = get_radar_service()
    return {"success": True, "watchlist": service.get_watchlist()}


@router.get("/radar/last")
async def get_last_radar_scan():
    """
    Last completed radar snapshot + locked ideas.
    Used to paint the UI immediately without wiping it during a new scan.
    """
    service = get_radar_service()
    last = service.get_last_scan() or service.get_cached_scan(max_age_seconds=14400) or {}
    from app.services.scan_jobs import get_scan_job_manager
    from app.services.symbol_store import get_harvest_meta, status as store_status
    from app.services.strategies.rsi_desk import weight_radar_rows

    if last:
        try:
            last = dict(last)
            def _need(rows):
                chunk = rows or []
                if not chunk:
                    return False
                return any(r.get("desk_score") is None for r in chunk[:12])

            if _need(last.get("flagged")):
                last["flagged"] = weight_radar_rows(last.get("flagged") or [])
            if _need(last.get("watch")):
                last["watch"] = weight_radar_rows(last.get("watch") or [])
            if _need(last.get("alert_box")):
                last["alert_box"] = weight_radar_rows(last.get("alert_box") or [])
        except Exception:
            pass

    running = get_scan_job_manager().find_running("radar")
    scan_running = bool(getattr(service, "_scan_running", False) or running)
    harvest = get_harvest_meta() or {}
    book = {}
    try:
        book = store_status()
    except Exception:
        book = {}
    # Mid-scan the live idea book is half-built — never merge it over the last full board.
    board = {} if scan_running else service.get_process_board(limit=8)
    if not last:
        return {
            "success": True,
            "has_data": False,
            "engine": "v4-process",
            "scan_running": scan_running,
            "active_job_id": running.id if running else None,
            "harvest": harvest,
            "book": book,
            **board,
        }
    return {
        "success": True,
        "has_data": True,
        **last,
        "scan_running": scan_running,
        "active_job_id": running.id if running else None,
        "harvest": harvest,
        "book": book,
        "ideas": last.get("ideas") or board.get("active") or [],
        "ideas_confirmed": last.get("ideas_confirmed") or board.get("confirmed") or [],
        "ideas_bullish": last.get("ideas_bullish") or board.get("bullish") or board.get("ideas_bullish") or [],
        "ideas_bearish": last.get("ideas_bearish") or board.get("bearish") or board.get("ideas_bearish") or [],
        "ideas_pullbacks": last.get("ideas_pullbacks") or board.get("pullbacks") or [],
        "ideas_watch": last.get("ideas_watch") or board.get("watch") or [],
        "ideas_conflict": last.get("ideas_conflict") or board.get("conflict") or [],
        "idea_counts": last.get("idea_counts") or board.get("counts") or {},
    }


def _publish_radar_hits(result: dict) -> None:
    """Notify locked process trades first; fall back to Grade A / A+."""
    try:
        from app.services.signal_bus import get_signal_bus

        bus = get_signal_bus()
        ideas = list(result.get("ideas") or [])
        if ideas:
            for idea in ideas[:5]:
                if idea.get("status") != "ACTIVE":
                    continue
                bus.publish(
                    source="process",
                    message=(
                        f"[LOCKED {idea.get('side')}] {idea.get('symbol')} "
                        f"{idea.get('strike')}{idea.get('opt_type')} — "
                        f"{(idea.get('recipe') or {}).get('name') or idea.get('label')} "
                        f"inv {idea.get('invalidation')} tgt {idea.get('target')}"
                    ),
                    level="signal",
                    symbol=idea.get("symbol"),
                    score=float(idea.get("composite") or idea.get("lis") or 0),
                    meta={
                        "strike": idea.get("strike"),
                        "type": idea.get("opt_type"),
                        "direction": idea.get("direction"),
                        "status": "ACTIVE",
                        "invalidation": idea.get("invalidation"),
                        "target": idea.get("target"),
                    },
                )
            return
        rows = list(result.get("flagged") or [])
        if not rows:
            rows = [
                r
                for r in (result.get("all_hits") or [])
                if r.get("grade") in ("A", "A+")
            ]
        for row in rows[:8]:
            grade = row.get("grade") or ""
            if grade not in ("A", "A+") and not row.get("actionable"):
                continue
            lis = float(row.get("lis") or 0)
            bus.publish(
                source="radar",
                message=(
                    f"[{grade}] LIS {lis:.0f} {row.get('symbol')} "
                    f"{row.get('strike')}{row.get('type')} — "
                    f"{(row.get('signal') or {}).get('label') or 'flow'} "
                    f"({row.get('direction') or ''})"
                ),
                level="signal",
                symbol=row.get("symbol"),
                score=lis,
                meta={
                    "strike": row.get("strike"),
                    "type": row.get("type"),
                    "grade": grade,
                    "direction": row.get("direction"),
                    "unusual_score": row.get("unusual_score"),
                },
            )
    except Exception:
        pass


@router.get("/radar/scan")
async def scan_all_symbols(
    min_lis: float = Query(0, description="Minimum LIS score to include (0–100)"),
    option_type: Optional[str] = Query(None, description="Filter: CE | PE | null for both"),
    strike_count: int = Query(14, description="Strikes above/below ATM per symbol"),
):
    """
    Blocking radar scan (legacy). Prefer POST /radar/scan/start for live progress.
    """
    import asyncio

    service = get_radar_service()
    result = await asyncio.to_thread(
        service.scan_all,
        None,
        min_lis,
        option_type,
        strike_count,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Scan failed"))
    _publish_radar_hits(result)
    return result


@router.post("/radar/scan")
async def scan_custom_symbols(body: ScanRequest):
    """
    Runs the radar on a custom list of symbols supplied by the client (blocking).
    """
    import asyncio

    service = get_radar_service()
    result = await asyncio.to_thread(
        service.scan_all,
        body.symbols,
        body.min_lis,
        body.option_type,
        body.strike_count,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Scan failed"))
    return result


@router.post("/radar/scan/start")
async def start_radar_scan_job(
    min_lis: float = Query(0),
    option_type: Optional[str] = Query(None),
    strike_count: int = Query(14, ge=4, le=20),
):
    """Nudge the harvest writer. Poll GET /radar/scan/jobs/{job_id} + /market/store/status."""
    import asyncio
    from app.services.fno_stocks import filter_valid_symbols
    from app.services.option_flow_radar import ALL_FNO_WATCHLIST
    from app.services.scan_jobs import get_scan_job_manager

    service = get_radar_service()
    watch = filter_valid_symbols(list(ALL_FNO_WATCHLIST))

    mgr = get_scan_job_manager()
    existing = mgr.find_running("radar")
    if existing:
        return {
            "success": True,
            "job_id": existing.id,
            "status": "running",
            "total": existing.total,
            "reused": True,
            "completed": existing.completed,
            "completion_pct": existing.completion_pct,
            "poll_url": f"/api/v1/radar/scan/jobs/{existing.id}",
        }
    if getattr(service, "_scan_running", False):
        return {
            "success": True,
            "job_id": None,
            "status": "blocked",
            "total": len(watch),
            "reused": True,
            "message": "A scan is already running — board stays frozen",
        }

    job = mgr.create(
        kind="radar",
        total=len(watch),
        label="option flow radar",
        meta={
            "min_lis": min_lis,
            "option_type": option_type,
            "strike_count": strike_count,
        },
        pending_symbols=list(watch),
    )
    mgr.mark_running(job.id)

    def _on_progress(scanned, total, symbol, flagged_row, err, status="ok", ms=0):
        import time as _time

        job_obj = mgr.get(job.id)
        meta = dict((job_obj.meta if job_obj else {}) or {})
        log = list(meta.get("log") or [])
        short = (symbol or "?").replace("NSE:", "").replace("-EQ", "").replace("-INDEX", "")
        if status != "start":
            log.append({
                "sym": short,
                "status": status,
                "ms": int(ms or 0),
                "err": (str(err)[:80] if err else None),
            })
        meta["log"] = log[-28:]
        meta["heartbeat_at"] = _time.time()
        meta["last_status"] = status
        meta["last_error"] = str(err)[:120] if err else None
        meta["last_ms"] = int(ms or 0)
        if status in ("wait", "retry", "retry_hit", "retry_start"):
            meta["phase"] = "wait"
        mgr.set_current(job.id, symbol)
        mgr.update(
            job.id,
            completed=scanned,
            completion_pct=round(100.0 * scanned / max(total, 1), 1),
            meta=meta,
        )
        if status in ("hit", "retry_hit", "skip") and symbol:
            mgr.clear_failed_symbol(job.id, symbol)
        if err and status not in ("start", "wait", "retry", "retry_start"):
            mgr.note_error_only(
                job.id,
                symbol or "?",
                str(err),
                rate_limited=("rate_limit" in str(err).lower() or str(err) == "timeout"),
            )

    async def _worker():
        try:
            result = await asyncio.to_thread(
                service.scan_all,
                None,
                min_lis,
                option_type,
                strike_count,
                _on_progress,
            )
            if not result.get("success"):
                mgr.finish(
                    job.id,
                    status="failed",
                    error_message=result.get("error", "Scan failed"),
                )
                return
            flagged = result.get("flagged") or []
            mgr.update(
                job.id,
                results=flagged,
                completed=int(result.get("scanned") or job.completed),
                rate_limited_skips=int(result.get("rate_limited_skips") or 0),
            )
            mgr.finish(
                job.id,
                status="completed",
                extra_meta={
                    "summary": {
                        "engine": result.get("engine"),
                        "scanned": result.get("scanned"),
                        "universe_requested": result.get("universe_requested"),
                        "total_flagged": result.get("total_flagged"),
                        "partial": result.get("partial"),
                        "completion_pct": result.get("completion_pct"),
                        "market_hours": result.get("market_hours"),
                        "timestamp": result.get("timestamp"),
                        "flagged": flagged,
                        "watch": result.get("watch") or [],
                        "alert_box": result.get("alert_box") or [],
                        "ideas": result.get("ideas") or [],
                        "ideas_confirmed": result.get("ideas_confirmed") or [],
                        "ideas_bullish": result.get("ideas_bullish") or [],
                        "ideas_bearish": result.get("ideas_bearish") or [],
                        "ideas_pullbacks": result.get("ideas_pullbacks") or [],
                        "ideas_watch": result.get("ideas_watch") or [],
                        "ideas_conflict": result.get("ideas_conflict") or [],
                        "idea_counts": result.get("idea_counts") or {},
                        "grade_counts": result.get("grade_counts"),
                        "rules": result.get("rules"),
                        "errors": result.get("errors"),
                        "rate_limited_skips": result.get("rate_limited_skips"),
                        "retry_attempted": result.get("retry_attempted") or 0,
                        "retry_recovered": result.get("retry_recovered") or 0,
                        "failed_remaining": result.get("failed_remaining") or [],
                    }
                },
            )
            _publish_radar_hits(result)
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
        "total": len(watch),
        "poll_url": f"/api/v1/radar/scan/jobs/{job.id}",
    }


@router.get("/radar/scan/jobs/{job_id}")
async def get_radar_scan_job(job_id: str):
    """Poll background radar job progress + flagged contracts."""
    from app.services.scan_jobs import get_scan_job_manager

    mgr = get_scan_job_manager()
    snap = mgr.snapshot(job_id, include_results=True)
    if not snap:
        raise HTTPException(status_code=404, detail="Job not found")

    meta = snap.get("meta") or {}
    summary = meta.get("summary") or {}
    done = snap["status"] in ("completed", "failed", "cancelled")
    # While the job is running, return progress only. A half-finished
    # flagged/idea list must not reach the board.
    flagged = (summary.get("flagged") or []) if done else []
    watch = (summary.get("watch") or []) if done else []
    alert_box = (summary.get("alert_box") or []) if done else []
    ideas = (summary.get("ideas") or []) if done else []

    return {
        "success": True,
        "engine": summary.get("engine") or "v4-process",
        "job_id": job_id,
        "status": snap["status"],
        "total": snap["total"],
        "completed": snap["completed"],
        "failed": snap["failed"],
        "rate_limited_skips": snap.get("rate_limited_skips", 0),
        "current_symbol": snap.get("current_symbol"),
        "completion_pct": snap.get("completion_pct")
        or summary.get("completion_pct")
        or 0,
        "partial": snap.get("partial") or summary.get("partial", False),
        "error_message": snap.get("error_message"),
        "scanned": summary.get("scanned", snap["completed"]) if done else snap["completed"],
        "universe_requested": summary.get("universe_requested", snap["total"]),
        "total_flagged": summary.get("total_flagged", len(flagged)) if done else 0,
        "flagged": flagged,
        "watch": watch,
        "alert_box": alert_box,
        "ideas": ideas,
        "ideas_confirmed": (summary.get("ideas_confirmed") or []) if done else [],
        "ideas_bullish": (summary.get("ideas_bullish") or []) if done else [],
        "ideas_bearish": (summary.get("ideas_bearish") or []) if done else [],
        "ideas_pullbacks": (summary.get("ideas_pullbacks") or []) if done else [],
        "ideas_watch": (summary.get("ideas_watch") or []) if done else [],
        "ideas_conflict": (summary.get("ideas_conflict") or []) if done else [],
        "idea_counts": (summary.get("idea_counts") or {}) if done else {},
        "grade_counts": summary.get("grade_counts") if done else None,
        "rules": summary.get("rules") if done else None,
        "errors": (summary.get("errors") or snap.get("errors")) if done else [],
        "retry_attempted": summary.get("retry_attempted") or 0,
        "retry_recovered": summary.get("retry_recovered") or 0,
        "failed_remaining": summary.get("failed_remaining") or snap.get("failed_symbols") or [],
        "market_hours": summary.get("market_hours"),
        "timestamp": summary.get("timestamp")
        or snap.get("finished_at")
        or snap.get("created_at"),
        "log": (meta.get("log") or [])[-28:],
        "last_status": meta.get("last_status"),
        "last_error": meta.get("last_error"),
        "last_ms": meta.get("last_ms"),
        "heartbeat_at": meta.get("heartbeat_at"),
        "phase": meta.get("phase"),
    }


@router.get("/radar/flow/{symbol:path}")
async def get_symbol_flow(
    symbol: str,
    strike_count: int = Query(14, description="Strikes above/below ATM"),
):
    """
    Get detailed option flow data for a single symbol.
    Returns: underlying data, option chain rows, flagged contracts, 5-min candles.
    Used for the stock chart + option chain widget when a row is selected.
    """
    service = get_radar_service()
    result = service.get_symbol_flow(symbol, strike_count)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result


@router.get("/radar/candles/{symbol:path}")
async def get_candles(
    symbol: str,
    resolution: str = Query("5", description="Resolution: 1, 5, 15, 60, D"),
    days: int = Query(1, description="Number of days of history"),
):
    """
    Returns OHLCV candlestick data for charting.
    Used to render the candlestick chart on the selected stock.
    """
    service = get_radar_service()
    result = service.get_candles(symbol, resolution, days)
    if not result.get("success", True):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result


@router.get("/radar/ideas")
async def get_process_ideas(limit: int = Query(12, ge=1, le=25)):
    """Locked Active Ideas board — the headline process trades."""
    return get_radar_service().get_process_board(limit=limit)


@router.get("/radar/ideas/{symbol:path}")
async def get_symbol_idea(symbol: str):
    """Single-symbol process idea + cached day map."""
    return get_radar_service().get_symbol_idea(symbol)


@router.get("/radar/levels/{symbol:path}")
async def get_institutional_levels(
    symbol: str,
    strike_count: int = Query(14, ge=4, le=20),
):
    """
    Full institutional map: pivots, Camarilla, CPR, PDH/PDL, VWAP, OR,
    OI walls, max pain, gamma, futures buildup.
    """
    import asyncio

    from app.services.levels import get_levels_service

    service = get_radar_service()

    def _build():
        ul = service._get_underlying_data(symbol, light=False)
        chain_resp = service.market_service.get_option_chain(symbol, strike_count)
        spot = float(
            (ul or {}).get("ltp")
            or chain_resp.get("spot_price")
            or 0
        )
        return get_levels_service().build_full_map(
            symbol,
            spot,
            chain=chain_resp.get("chain") or [],
            candles_5m=(ul or {}).get("candles_5min") or [],
        )

    full = await asyncio.to_thread(_build)
    return {"success": True, "symbol": symbol, **full}


@router.post("/radar/backtest")
async def backtest_signal(body: BacktestRequest):
    """
    For a past flagged signal, computes forward returns of the underlying.
    Returns 15-min, 30-min, 60-min returns from the signal timestamp.
    """
    service = get_radar_service()
    result = service.backtest_signal(
        symbol=body.symbol,
        strike=body.strike,
        opt_type=body.option_type,
        signal_timestamp=body.signal_timestamp,
        forward_minutes=body.forward_minutes,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Backtest failed"))
    return result
