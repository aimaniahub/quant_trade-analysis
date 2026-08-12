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
    strike_count: int = 8


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


def _publish_radar_hits(result: dict) -> None:
    try:
        from app.services.signal_bus import get_signal_bus

        bus = get_signal_bus()
        for row in (result.get("flagged") or [])[:5]:
            lis = float(row.get("lis") or 0)
            conviction = (row.get("conviction") or {}).get("level") or ""
            if lis >= 70 or conviction == "HIGH":
                bus.publish(
                    source="radar",
                    message=(
                        f"LIS {lis:.0f} {row.get('symbol')} "
                        f"{row.get('strike')}{row.get('type')} — "
                        f"{(row.get('signal') or {}).get('label') or row.get('signal') or 'flow'}"
                    ),
                    level="signal",
                    symbol=row.get("symbol"),
                    score=lis,
                    meta={"strike": row.get("strike"), "type": row.get("type")},
                )
    except Exception:
        pass


@router.get("/radar/scan")
async def scan_all_symbols(
    min_lis: float = Query(0, description="Minimum LIS score to include (0–100)"),
    option_type: Optional[str] = Query(None, description="Filter: CE | PE | null for both"),
    strike_count: int = Query(8, description="Strikes above/below ATM per symbol"),
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
    strike_count: int = Query(8, ge=4, le=20),
):
    """Start background radar scan. Poll GET /radar/scan/jobs/{job_id}."""
    import asyncio
    from app.services.fno_stocks import filter_valid_symbols
    from app.services.option_flow_radar import ALL_FNO_WATCHLIST
    from app.services.scan_jobs import get_scan_job_manager

    service = get_radar_service()
    watch = filter_valid_symbols(list(ALL_FNO_WATCHLIST))

    mgr = get_scan_job_manager()
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

    def _on_progress(scanned, total, symbol, flagged_row, err):
        mgr.set_current(job.id, symbol)
        mgr.update(
            job.id,
            completed=scanned,
            completion_pct=round(100.0 * scanned / max(total, 1), 1),
        )
        if flagged_row:
            mgr.append_result_raw(job.id, flagged_row)
        if err:
            mgr.note_error_only(
                job.id,
                symbol or "?",
                str(err),
                rate_limited=("rate_limit" in str(err).lower()),
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
                        "scanned": result.get("scanned"),
                        "universe_requested": result.get("universe_requested"),
                        "total_flagged": result.get("total_flagged"),
                        "partial": result.get("partial"),
                        "completion_pct": result.get("completion_pct"),
                        "market_hours": result.get("market_hours"),
                        "timestamp": result.get("timestamp"),
                        "flagged": flagged,
                        "errors": result.get("errors"),
                        "rate_limited_skips": result.get("rate_limited_skips"),
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
    flagged = summary.get("flagged") or snap.get("results") or []

    return {
        "success": True,
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
        "scanned": summary.get("scanned", snap["completed"]),
        "universe_requested": summary.get("universe_requested", snap["total"]),
        "total_flagged": summary.get("total_flagged", len(flagged)),
        "flagged": flagged,
        "errors": summary.get("errors") or snap.get("errors"),
        "market_hours": summary.get("market_hours"),
        "timestamp": summary.get("timestamp")
        or snap.get("finished_at")
        or snap.get("created_at"),
    }


@router.get("/radar/flow/{symbol:path}")
async def get_symbol_flow(
    symbol: str,
    strike_count: int = Query(10, description="Strikes above/below ATM"),
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
