"""
MA Crossover REST + WebSocket Routes
=====================================
GET  /api/v1/ma-crossover/status         – service status & config
GET  /api/v1/ma-crossover/crossovers     – latest detected crossovers
GET  /api/v1/ma-crossover/nearing        – nearing crossover watchlist
POST /api/v1/ma-crossover/start          – start the scan loop
POST /api/v1/ma-crossover/stop           – stop the scan loop
PUT  /api/v1/ma-crossover/config         – update configuration
WS   /api/v1/ws/ma-crossover             – real-time push channel
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.services.strategies.ma_crossover import get_ma_crossover_service
from app.utils.market_hours import is_market_open, market_open_time_ist

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# WebSocket connection manager (MA-Crossover channel)
# ---------------------------------------------------------------------------

class MACrossoverConnectionManager:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, data: Dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ma_crossover_manager = MACrossoverConnectionManager()


# Register the broadcast callback once the module loads so the service can
# push events to WS clients without importing router-level names.
async def _ws_broadcast(event: Dict):
    if event.get("is_progress_update"):
        await ma_crossover_manager.broadcast({
            "type": "scan_progress",
            "data": event["progress"]
        })
    else:
        await ma_crossover_manager.broadcast({
            "type": "ma_crossover",
            "data": event,
        })


# Wire service → websocket channel
_svc = get_ma_crossover_service()
_svc.set_broadcast_callback(_ws_broadcast)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ConfigUpdate(BaseModel):
    ma_short_type: Optional[str] = None
    ma_short_period: Optional[int] = None
    ma_long_type: Optional[str] = None
    ma_long_period: Optional[int] = None
    ma_trend_type: Optional[str] = None
    ma_trend_period: Optional[int] = None
    timeframes: Optional[List[str]] = None
    proximity_threshold: Optional[float] = None
    consecutive_candles: Optional[int] = None
    cooldown_minutes: Optional[int] = None
    scan_batch_size: Optional[int] = None
    scan_interval_secs: Optional[int] = None
    auto_scan_top_only: Optional[bool] = None
    auto_scan_chunk_size: Optional[int] = None


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@router.get("/ma-crossover/status")
async def ma_crossover_status():
    """Return service status, current config, and market-hours info."""
    svc = get_ma_crossover_service()
    status = svc.get_status()
    status["market_info"] = market_open_time_ist()
    return status


@router.get("/ma-crossover/crossovers")
async def get_crossovers(limit: int = 100):
    """Return the latest confirmed MA crossovers."""
    svc = get_ma_crossover_service()
    data = svc.get_crossovers()[:limit]
    return {"count": len(data), "crossovers": data}


@router.get("/ma-crossover/nearing")
async def get_nearing(limit: int = 50):
    """Return the nearing-crossover watchlist."""
    svc = get_ma_crossover_service()
    data = svc.get_nearing()[:limit]
    return {"count": len(data), "nearing": data}


@router.post("/ma-crossover/start")
async def start_service():
    """Start the MA crossover scan loop."""
    svc = get_ma_crossover_service()
    if svc.get_status()["running"]:
        return {"status": "already_running"}
    await svc.start()
    return {"status": "started"}


@router.post("/ma-crossover/stop")
async def stop_service():
    """Stop the MA crossover scan loop."""
    svc = get_ma_crossover_service()
    await svc.stop()
    return {"status": "stopped"}


@router.post("/ma-crossover/scan")
async def trigger_scan():
    """Trigger a manual MA crossover scan immediately in the background."""
    svc = get_ma_crossover_service()
    if not svc.market_service._get_fyers():
        raise HTTPException(status_code=400, detail="Fyers API is not authenticated. Please log in first.")
    
    triggered = await svc.trigger_manual_scan()
    if not triggered:
        return {"status": "already_scanning", "message": "A scan is already in progress."}
    return {"status": "scanning", "message": "Manual scan triggered successfully."}



@router.put("/ma-crossover/config")
async def update_config(body: ConfigUpdate):
    """Update scanner configuration (hot-reload)."""
    svc = get_ma_crossover_service()
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields provided")
    svc.update_config(updates)
    return {"status": "updated", "config": svc.get_config()}


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/ma-crossover")
async def ws_ma_crossover(websocket: WebSocket):
    """
    Real-time MA crossover push channel.
    On connect, immediately sends current snapshot then pushes live events.
    """
    await ma_crossover_manager.connect(websocket)
    svc = get_ma_crossover_service()

    # Send initial snapshot
    try:
        await websocket.send_json({
            "type": "snapshot",
            "crossovers": svc.get_crossovers()[:50],
            "nearing": svc.get_nearing()[:30],
            "status": svc.get_status(),
        })
    except Exception:
        ma_crossover_manager.disconnect(websocket)
        return

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            if action == "ping":
                await websocket.send_json({"type": "pong"})
            elif action == "get_snapshot":
                await websocket.send_json({
                    "type": "snapshot",
                    "crossovers": svc.get_crossovers()[:50],
                    "nearing": svc.get_nearing()[:30],
                })
            elif action == "update_config":
                cfg = data.get("config", {})
                svc.update_config(cfg)
                await websocket.send_json({
                    "type": "config_updated",
                    "config": svc.get_config(),
                })
    except WebSocketDisconnect:
        ma_crossover_manager.disconnect(websocket)
    except Exception as exc:
        logger.error(f"[MA WS] error: {exc}")
        ma_crossover_manager.disconnect(websocket)
