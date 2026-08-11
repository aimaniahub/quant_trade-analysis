"""
Confluence REST API
===================
GET  /confluence              – multi-source scored cards
GET  /confluence/status       – radar scheduler + cache status
POST /confluence/radar/scan   – trigger scheduled-style radar scan now
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.confluence import get_confluence_engine
from app.services.radar_scheduler import get_radar_scheduler
from app.services.option_flow_radar import get_radar_service

router = APIRouter()


class ConfluenceRequest(BaseModel):
    symbols: Optional[List[str]] = None
    min_sources: int = 2


@router.get("/confluence")
async def get_confluence(
    min_sources: int = Query(2, ge=1, le=4),
    include_nifty_state: bool = Query(True),
):
    """
    Rank symbols by multi-source confluence (MA + radar cache + intelligence + bus).
    """
    import asyncio

    engine = get_confluence_engine()
    try:
        # Intelligence NIFTY call can block; run in thread
        result = await asyncio.to_thread(
            engine.evaluate,
            None,
            min_sources,
            include_nifty_state,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/confluence")
async def post_confluence(body: ConfluenceRequest):
    import asyncio

    engine = get_confluence_engine()
    try:
        result = await asyncio.to_thread(
            engine.evaluate,
            body.symbols,
            body.min_sources,
            True,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/confluence/status")
async def confluence_status():
    scheduler = get_radar_scheduler()
    radar = get_radar_service()
    return {
        "success": True,
        "scheduler": scheduler.get_status(),
        "radar_last_scan": radar.get_last_scan(),
    }


@router.post("/confluence/radar/scan")
async def trigger_scheduled_radar():
    """Trigger a TOP-FNO radar pass (same as background scheduler)."""
    scheduler = get_radar_scheduler()
    result = await scheduler.run_once()
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Scan failed"))
    return result
