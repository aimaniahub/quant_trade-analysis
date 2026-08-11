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


@router.get("/radar/scan")
async def scan_all_symbols(
    min_lis: float = Query(0, description="Minimum LIS score to include (0–100)"),
    option_type: Optional[str] = Query(None, description="Filter: CE | PE | null for both"),
    strike_count: int = Query(8, description="Strikes above/below ATM per symbol"),
):
    """
    Runs the Option Flow Radar scan across the default watchlist.
    Returns flagged contracts sorted by LIS (Leading Indicator Score).
    This is the primary endpoint for the Live Monitor tab.
    """
    import asyncio
    from app.services.signal_bus import get_signal_bus

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

    # Publish high-conviction radar hits
    try:
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

    return result


@router.post("/radar/scan")
async def scan_custom_symbols(body: ScanRequest):
    """
    Runs the radar on a custom list of symbols supplied by the client.
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
