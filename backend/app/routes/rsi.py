"""
RSI desk API — harvest book only. No Fyers job.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/strategies/rsi/scan")
async def scan_rsi_book(
    source: str = Query("full", description="full | top"),
    limit: int = Query(200, ge=10, le=250),
    side: str = Query("both", description="both | oversold | overbought"),
):
    """CPU RSI(14) 15m + derived 1H × stored OC/MTF. Poll every ~45s."""
    from app.services.strategies.rsi_desk import scan_book

    if source not in ("full", "top"):
        raise HTTPException(status_code=400, detail="source must be full or top")
    result = await asyncio.to_thread(scan_book, source=source, limit=limit)
    want = (side or "both").lower()
    if want in ("oversold", "bounce"):
        for key in ("trade", "watch", "reject"):
            result[key] = [r for r in result.get(key) or [] if r.get("thesis") == "BOUNCE"]
        result["counts"]["trade"] = len(result["trade"])
        result["counts"]["watch"] = len(result["watch"])
        result["counts"]["reject"] = len(result["reject"])
    elif want in ("overbought", "fade"):
        for key in ("trade", "watch", "reject"):
            result[key] = [r for r in result.get(key) or [] if r.get("thesis") == "FADE"]
        result["counts"]["trade"] = len(result["trade"])
        result["counts"]["watch"] = len(result["watch"])
        result["counts"]["reject"] = len(result["reject"])
    return result


@router.get("/strategies/rsi/divergence")
async def scan_rsi_divergence(
    tf: str = Query("15", description="15 | D"),
    source: str = Query("full", description="full | top"),
    limit: int = Query(200, ge=10, le=250),
):
    """Classic RSI divergence on harvested 15m or daily. No Fyers."""
    from app.services.strategies.rsi_desk import scan_divergence_book

    tf_key = "D" if str(tf).upper() in ("D", "1D", "DAY", "DAILY", "1") else "15"
    if source not in ("full", "top"):
        raise HTTPException(status_code=400, detail="source must be full or top")
    return await asyncio.to_thread(scan_divergence_book, tf=tf_key, source=source, limit=limit)


@router.get("/strategies/rsi/symbol/{symbol:path}")
async def explain_rsi_symbol(symbol: str):
    """Re-score one name from the store."""
    from app.services.strategies.rsi_desk import evaluate_symbol

    result = await asyncio.to_thread(evaluate_symbol, symbol)
    if not result.get("success") and result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result
