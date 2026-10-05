"""Paper Trade Watch routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.trade_watch import flatten, mark_and_exit, refresh_open_prices, run_pick, snapshot

router = APIRouter()


class RunBody(BaseModel):
    force: bool = False


@router.get("/trade-watch")
async def get_trade_watch(live: bool = True):
    """Desk snapshot. live=true (default) reprices OPEN trades from the chain."""
    body = refresh_open_prices() if live else snapshot(skip_px=True)
    return {"success": True, **body}


@router.post("/trade-watch/run")
async def run_trade_watch(body: RunBody | None = None):
    force = bool(body.force) if body else False
    try:
        return {"success": True, **run_pick(force=force)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:240]) from exc


@router.post("/trade-watch/mark")
async def mark_trade_watch():
    return {"success": True, **mark_and_exit(ask_ai=True)}


@router.post("/trade-watch/flatten")
async def flatten_trade_watch():
    return {"success": True, **flatten("Manual square-off")}
