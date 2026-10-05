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
    last = service.get_last_scan() or service.get_cached_scan(max_age_seconds=259200) or {}
    from app.services.scan_jobs import get_scan_job_manager
    from app.services.symbol_store import get_harvest_meta, status as store_status
    if last:
        last = dict(last)
        last.setdefault("tradeable", last.get("flagged") or [])

    running = get_scan_job_manager().find_running("radar")
    scan_running = bool(getattr(service, "_scan_running", False) or running)
    harvest = get_harvest_meta() or {}
    book = {}
    try:
        book = store_status()
    except Exception:
        book = {}
    if not last:
        return {
            "success": True,
            "has_data": False,
            "engine": "v6-anomaly",
            "scan_running": scan_running,
            "active_job_id": running.id if running else None,
            "harvest": harvest,
            "book": book,
            "tradeable": [],
            "flagged": [],
            "watch": [],
        }
    last.setdefault("tradeable", last.get("flagged") or [])
    flow = list(last.get("tradeable") or []) + list(last.get("watch") or [])
    last.setdefault("bullish", [h for h in flow if (h or {}).get("chain_bias") == "BULLISH"])
    last.setdefault("bearish", [h for h in flow if (h or {}).get("chain_bias") == "BEARISH"])
    last.setdefault("top", (last.get("tradeable") or flow)[:8])
    last.setdefault("screen", last.get("screen") or flow)
    last.setdefault("unique", [h for h in flow if ((h or {}).get("flags") or {}).get("unique")][:12])
    return {
        "success": True,
        "has_data": True,
        **last,
        "engine": last.get("engine") or "v6-anomaly",
        "scan_running": scan_running,
        "active_job_id": running.id if running else None,
        "harvest": harvest,
        "book": book,
        "tradeable": last.get("tradeable") or last.get("flagged") or [],
        "flagged": last.get("tradeable") or last.get("flagged") or [],
        "bullish": last.get("bullish") or [],
        "bearish": last.get("bearish") or [],
        "top": last.get("top") or [],
        "screen": last.get("screen") or [],
        "unique": last.get("unique") or [],
        "ideas": last.get("ideas") or [],
        "data_mode": last.get("data_mode"),
        "as_of": last.get("as_of"),
        "session_date": last.get("session_date"),
        "next_open": last.get("next_open"),
    }


def _publish_radar_hits(result: dict) -> None:
    try:
        from app.services.signal_bus import get_signal_bus

        bus = get_signal_bus()
        rows = list(result.get("tradeable") or result.get("flagged") or [])
        for row in rows[:8]:
            if row.get("grade") != "TRADEABLE":
                continue
            trade = row.get("trade") or {}
            bus.publish(
                source="radar",
                message=(
                    f"[TRADEABLE {row.get('chain_bias')}] {row.get('name') or row.get('symbol')} "
                    f"{trade.get('action') or ''} {trade.get('strike') or ''} "
                    f"— {(row.get('top_anomaly') or {}).get('label') or row.get('regime')}"
                ),
                level="signal",
                symbol=row.get("symbol"),
                score=float((row.get("top_anomaly") or {}).get("oi_added") or 0),
                meta={
                    "grade": row.get("grade"),
                    "bias": row.get("chain_bias"),
                    "strike": trade.get("strike"),
                    "invalidation": trade.get("invalidation"),
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
    """Nudge the single harvest actor and return the live board (non-blocking)."""
    from app.services.radar_scheduler import get_radar_scheduler

    service = get_radar_service()
    started = await get_radar_scheduler().ensure_pass(
        source="legacy_get",
        min_lis=min_lis,
        option_type=option_type,
        strike_count=strike_count,
    )
    if not started.get("success"):
        raise HTTPException(status_code=400, detail=started.get("error", "Scan failed"))
    last = service.get_last_scan() or {}
    return {
        "success": True,
        "job_id": started.get("job_id"),
        "reused": started.get("reused"),
        "scan_running": True,
        **last,
    }


@router.post("/radar/scan")
async def scan_custom_symbols(body: ScanRequest):
    """
    Custom lists still go through the single harvest lock.
    A full-universe pass already running is reused instead of a second walk.
    """
    from app.services.radar_scheduler import get_radar_scheduler
    from app.services.scan_jobs import get_scan_job_manager

    service = get_radar_service()
    mgr = get_scan_job_manager()
    if mgr.find_running("radar") or getattr(service, "_scan_running", False):
        started = await get_radar_scheduler().ensure_pass(source="custom_busy")
        last = service.get_last_scan() or {}
        return {
            "success": True,
            "reused": True,
            "job_id": started.get("job_id"),
            "message": "Full harvest already running — custom list not started",
            **last,
        }

    started = await get_radar_scheduler().ensure_pass(
        source="custom",
        min_lis=body.min_lis,
        option_type=body.option_type,
        strike_count=body.strike_count,
    )
    last = service.get_last_scan() or {}
    return {
        "success": True,
        "job_id": started.get("job_id"),
        "reused": started.get("reused"),
        "scan_running": True,
        **last,
    }


@router.post("/radar/scan/start")
async def start_radar_scan_job(
    min_lis: float = Query(0),
    option_type: Optional[str] = Query(None),
    strike_count: int = Query(14, ge=4, le=20),
):
    """Nudge the single harvest actor. Poll GET /radar/scan/jobs/{job_id}."""
    from app.services.radar_scheduler import get_radar_scheduler

    started = await get_radar_scheduler().ensure_pass(
        source="ui",
        min_lis=min_lis,
        option_type=option_type,
        strike_count=strike_count,
    )
    if not started.get("success"):
        raise HTTPException(status_code=400, detail=started.get("error", "Scan failed"))
    return started


@router.get("/radar/scan/jobs/{job_id}")
async def get_radar_scan_job(job_id: str):
    """Poll harvest job. Live flagged / symbol_states are visible while running."""
    from app.services.scan_jobs import get_scan_job_manager

    mgr = get_scan_job_manager()
    snap = mgr.snapshot(job_id, include_results=True)
    if not snap:
        raise HTTPException(status_code=404, detail="Job not found")

    meta = snap.get("meta") or {}
    summary = meta.get("summary") or {}
    done = snap["status"] in ("completed", "failed", "cancelled", "interrupted")
    last = get_radar_service().get_last_scan() or {}

    def _pick(key, default=None):
        if done and summary.get(key) is not None:
            return summary.get(key)
        if last.get(key) is not None:
            return last.get(key)
        return default

    flagged = _pick("tradeable", None) or _pick("flagged", []) or []
    watch = _pick("watch", []) or []
    alert_box = _pick("alert_box", []) or []
    ideas = _pick("ideas", []) or []

    return {
        "success": True,
        "engine": summary.get("engine") or last.get("engine") or "v6-anomaly",
        "job_id": job_id,
        "status": snap["status"],
        "total": snap["total"] or last.get("universe_requested") or last.get("total"),
        "completed": snap["completed"],
        "failed": snap["failed"],
        "rate_limited_skips": snap.get("rate_limited_skips", 0),
        "current_symbol": snap.get("current_symbol"),
        "completion_pct": snap.get("completion_pct")
        or summary.get("completion_pct")
        or last.get("completion_pct")
        or 0,
        "partial": bool(_pick("partial", snap.get("partial"))),
        "error_message": snap.get("error_message"),
        "scanned": _pick("scanned", snap["completed"]),
        "attempted": _pick("attempted", snap["completed"]),
        "ok_chain": _pick("ok_chain", 0),
        "hits": _pick("hits", len(flagged)),
        "universe_requested": _pick("universe_requested", snap["total"]),
        "total_flagged": _pick("total_flagged", len(flagged)),
        "flagged": flagged,
        "tradeable": flagged,
        "bullish": _pick("bullish", []) or [],
        "bearish": _pick("bearish", []) or [],
        "top": _pick("top", []) or [],
        "watch": watch,
        "quiet_count": _pick("quiet_count", 0) or 0,
        "flow": _pick("flow", []) or [],
        "screen": _pick("screen", []) or [],
        "alert_box": alert_box,
        "ideas": ideas,
        "ideas_confirmed": _pick("ideas_confirmed", []) or [],
        "ideas_bullish": _pick("ideas_bullish", []) or [],
        "ideas_bearish": _pick("ideas_bearish", []) or [],
        "ideas_pullbacks": _pick("ideas_pullbacks", []) or [],
        "ideas_watch": _pick("ideas_watch", []) or [],
        "ideas_conflict": _pick("ideas_conflict", []) or [],
        "idea_counts": _pick("idea_counts", {}) or {},
        "grade_counts": _pick("grade_counts"),
        "symbol_states": _pick("symbol_states", []) or [],
        "skipped": _pick("skipped", []) or [],
        "telemetry": _pick("telemetry", {}) or {},
        "rules": _pick("rules"),
        "errors": _pick("errors", snap.get("errors")) or [],
        "retry_attempted": _pick("retry_attempted", 0) or 0,
        "retry_recovered": _pick("retry_recovered", 0) or 0,
        "failed_remaining": _pick("failed_remaining", []) or [],
        "market_hours": _pick("market_hours"),
        "timestamp": _pick("timestamp")
        or snap.get("finished_at")
        or snap.get("created_at"),
        "log": (meta.get("log") or [])[-28:],
        "last_status": meta.get("last_status"),
        "last_error": meta.get("last_error"),
        "last_ms": meta.get("last_ms"),
        "heartbeat_at": meta.get("heartbeat_at"),
        "phase": meta.get("phase") or last.get("phase"),
        "scan_running": not done,
        "has_data": bool(
            flagged or watch or ideas or _pick("flow") or last.get("symbol_states")
        ),
    }


@router.get("/radar/flow/{symbol:path}")
async def get_symbol_flow(
    symbol: str,
    strike_count: int = Query(14, description="Strikes above/below ATM"),
    live: bool = Query(False, description="Explicit live/debug fetch; ignored during harvest"),
):
    """
    Get detailed option flow data for a single symbol.
    Store-first. live=1 may hit Fyers only when the harvest actor is idle.
    """
    service = get_radar_service()
    result = service.get_symbol_flow(symbol, strike_count, live=live)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result


@router.get("/radar/candles/{symbol:path}")
async def get_candles(
    symbol: str,
    resolution: str = Query("15", description="Resolution: 15, 60, D (5m is not harvested)"),
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
        from app.services import symbol_store as store

        chain_resp = store.get_chain(symbol, strike_count) or {}
        spot_row = store.get_spot(symbol) or {}
        m15 = store.get_history(symbol, "15", min_bars=1) or []
        spot = float(
            spot_row.get("ltp")
            or chain_resp.get("spot_price")
            or 0
        )
        return get_levels_service().build_full_map(
            symbol,
            spot,
            chain=chain_resp.get("chain") or [],
            candles_5m=m15,
            fetch_futures=False,
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
