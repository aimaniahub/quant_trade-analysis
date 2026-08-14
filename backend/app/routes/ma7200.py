"""
15m 7/200 MA Cross + Option Chain Confirmation API

Direct Fyers history calls + background job progress.
Filter knobs: fast_ma, slow_ma, window_days, vol_mult, max_bars_ago.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
import asyncio

router = APIRouter()


def _scan_kwargs(
    *,
    limit: int,
    lookback: int,
    source: str,
    fast_ma: int,
    slow_ma: int,
    window_days: int,
    vol_mult: float,
    max_bars_ago: int,
    history_days: int,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "limit": limit,
        "lookback_crosses": lookback,
        "source": source,
        "history_days": history_days,
        "fast_ma": fast_ma,
        "slow_ma": slow_ma,
        "window_days": window_days,
        "vol_mult": vol_mult,
        "max_bars_ago": max_bars_ago,
        **({"job_id": job_id} if job_id else {}),
    }


@router.post("/strategies/ma7200/scan/start")
async def start_ma7200_scan(
    limit: int = Query(200, ge=5, le=250),
    lookback: int = Query(12, ge=1, le=24),
    source: str = Query("full", description="full | top"),
    fast_ma: int = Query(7, ge=2, le=100, description="Fast EMA period"),
    slow_ma: int = Query(200, ge=5, le=500, description="Slow EMA period"),
    window_days: int = Query(15, ge=1, le=90, description="First-cross window (calendar days)"),
    vol_mult: float = Query(1.5, ge=0.5, le=10.0, description="Volume vs prior 10-bar avg"),
    max_bars_ago: int = Query(1, ge=0, le=20, description="Max age: bars_ago 0..N"),
    history_days: int = Query(40, ge=10, le=120, description="History fetch days"),
):
    """
    Start direct-API scan of F&O equities (15m history each).
    Poll GET /strategies/ma7200/scan/jobs/{job_id} for progress.
    """
    from app.services.scan_jobs import get_scan_job_manager
    from app.services.strategies.ma7200_scanner import get_ma7200_scanner
    from app.services.fno_stocks import filter_valid_symbols, get_fno_stocks, TOP_FNO_STOCKS

    if slow_ma <= fast_ma:
        raise HTTPException(status_code=400, detail="slow_ma must be greater than fast_ma")

    if source == "top":
        n = len(filter_valid_symbols(list(TOP_FNO_STOCKS))[:limit])
    else:
        n = len(filter_valid_symbols(list(get_fno_stocks(top_only=False)))[:limit])

    settings = {
        "source": source,
        "limit": limit,
        "lookback": lookback,
        "fast_ma": fast_ma,
        "slow_ma": slow_ma,
        "window_days": window_days,
        "vol_mult": vol_mult,
        "max_bars_ago": max_bars_ago,
        "history_days": history_days,
    }

    mgr = get_scan_job_manager()
    job = mgr.create(
        kind="ma7200",
        total=n,
        label=f"ma7200 {fast_ma}/{slow_ma} {window_days}d vol{vol_mult}",
        meta=settings,
    )
    mgr.mark_running(job.id)
    svc = get_ma7200_scanner()
    kwargs = _scan_kwargs(
        limit=limit,
        lookback=lookback,
        source=source,
        fast_ma=fast_ma,
        slow_ma=slow_ma,
        window_days=window_days,
        vol_mult=vol_mult,
        max_bars_ago=max_bars_ago,
        history_days=history_days,
        job_id=job.id,
    )

    async def _worker():
        try:
            await asyncio.to_thread(svc.scan_universe, **kwargs)
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
        "total": n,
        "source": source,
        "mode": "direct_api",
        "settings": settings,
        "poll_url": f"/api/v1/strategies/ma7200/scan/jobs/{job.id}",
        "note": "Direct Fyers 15m history per symbol — poll for progress",
    }


@router.get("/strategies/ma7200/scan/jobs/{job_id}")
async def get_ma7200_job(job_id: str):
    """Poll direct-API scan progress + candidates."""
    from app.services.scan_jobs import get_scan_job_manager

    mgr = get_scan_job_manager()
    snap = mgr.snapshot(job_id, include_results=True)
    if not snap:
        raise HTTPException(status_code=404, detail="Job not found")

    summary = (snap.get("meta") or {}).get("summary") or {}
    candidates = summary.get("candidates") or snap.get("results") or []
    job_meta = snap.get("meta") or {}

    return {
        "success": True,
        "job_id": job_id,
        "status": snap["status"],
        "total": snap["total"],
        "completed": snap["completed"],
        "current_symbol": snap.get("current_symbol"),
        "completion_pct": snap.get("completion_pct") or 0,
        "candidates": candidates,
        "count": len(candidates),
        "scanned": summary.get("scanned", snap["completed"]),
        "universe": summary.get("universe", snap["total"]),
        "api": summary.get("api"),
        "rules": summary.get("rules"),
        "errors": summary.get("errors") or snap.get("errors"),
        "error_count": summary.get("error_count") or snap.get("error_count") or 0,
        "error_message": snap.get("error_message"),
        "params": summary.get("params") or {
            k: job_meta.get(k)
            for k in (
                "fast_ma",
                "slow_ma",
                "window_days",
                "vol_mult",
                "max_bars_ago",
                "source",
                "limit",
            )
            if k in job_meta
        },
        "timestamp": summary.get("timestamp") or snap.get("finished_at"),
        "note": summary.get("note"),
    }


@router.get("/strategies/ma7200/scan")
async def scan_ma7200_crosses(
    limit: int = Query(200, ge=5, le=250),
    lookback: int = Query(12, ge=1, le=24),
    source: str = Query("full", description="full | top"),
    fast_ma: int = Query(7, ge=2, le=100),
    slow_ma: int = Query(200, ge=5, le=500),
    window_days: int = Query(15, ge=1, le=90),
    vol_mult: float = Query(1.5, ge=0.5, le=10.0),
    max_bars_ago: int = Query(1, ge=0, le=20),
    history_days: int = Query(40, ge=10, le=120),
):
    """
    Blocking direct-API scan (prefer /scan/start + poll for long runs).
    """
    from app.services.strategies.ma7200_scanner import get_ma7200_scanner

    if slow_ma <= fast_ma:
        raise HTTPException(status_code=400, detail="slow_ma must be greater than fast_ma")

    svc = get_ma7200_scanner()
    try:
        return await asyncio.to_thread(
            svc.scan_universe,
            **_scan_kwargs(
                limit=limit,
                lookback=lookback,
                source=source,
                fast_ma=fast_ma,
                slow_ma=slow_ma,
                window_days=window_days,
                vol_mult=vol_mult,
                max_bars_ago=max_bars_ago,
                history_days=history_days,
            ),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies/ma7200/settings/defaults")
async def ma7200_settings_defaults():
    """Default filter knobs for the UI settings panel."""
    from app.services.strategies.ma7200_scanner import (
        FAST_PERIOD,
        SLOW_PERIOD,
        FIRST_CROSS_WINDOW_DAYS,
        VOL_MULT,
        HISTORY_DAYS,
    )

    return {
        "success": True,
        "defaults": {
            "fast_ma": FAST_PERIOD,
            "slow_ma": SLOW_PERIOD,
            "window_days": FIRST_CROSS_WINDOW_DAYS,
            "vol_mult": VOL_MULT,
            "max_bars_ago": 1,
            "history_days": HISTORY_DAYS,
        },
        "ranges": {
            "fast_ma": {"min": 2, "max": 100},
            "slow_ma": {"min": 5, "max": 500},
            "window_days": {"min": 1, "max": 90},
            "vol_mult": {"min": 0.5, "max": 10},
            "max_bars_ago": {"min": 0, "max": 20},
            "history_days": {"min": 10, "max": 120},
        },
    }


@router.get("/strategies/ma7200/analyze")
async def analyze_chain_for_cross(
    symbol: str = Query(...),
    cross_type: str = Query(...),
    strike_count: int = Query(12, ge=5, le=20),
):
    """Option chain confirmation for a MA-cross candidate."""
    from app.services.strategies.ma7200_scanner import get_ma7200_scanner

    svc = get_ma7200_scanner()
    try:
        result = await asyncio.to_thread(
            svc.confirm_with_option_chain,
            symbol,
            cross_type,
            strike_count=strike_count,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=400, detail=result.get("error") or "Analyze failed"
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
