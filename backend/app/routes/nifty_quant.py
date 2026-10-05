"""
Nifty 50 Quant API Endpoints.
Serves deep quant analytics, strike color matrices, heavyweight impact calculations,
and breakout simulations.
"""

import asyncio
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.nifty_quant_service import get_nifty_quant_service

router = APIRouter()
quant_service = get_nifty_quant_service()

class BreakoutSimulationRequest(BaseModel):
    stock_symbol: str
    expected_move_pct: float

@router.get("/options/nifty-quant")
async def get_nifty_quant_matrix(force_refresh: bool = Query(False, description="Bypass store cache and fetch fresh live option chains & quotes")):
    """
    Get real-time quantitative option chain analysis for Nifty 50.
    Returns:
        - Exact Black-Scholes Greeks per strike
        - 4-Quadrant Strike Classification (LBU, SBU, SH-COV, LUW, GAMMA_EXPLOSION)
        - Heavyweight stock point contribution (Top 10 weights)
        - ATM Straddle Fair-Value VWAP & Skew Ratio
        - Analytical Max Pain with strike pinning
        - Trap Detection (Call Traps & Put Traps)
        - Greeks-optimized Best Trade Recommendation
    """
    try:
        result = await asyncio.to_thread(quant_service.get_full_quant_matrix, force_refresh)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate Nifty quant matrix: {str(e)}")

@router.post("/options/nifty-quant/simulate")
async def simulate_breakout(req: BreakoutSimulationRequest):
    """
    What-If Simulator:
    Given an expected stock breakout %, calculates the projected point rally on Nifty,
    target Nifty level, and the optimal strike price to execute.
    """
    try:
        matrix = await asyncio.to_thread(quant_service.get_full_quant_matrix)
        spot = matrix.get("spot_price") or 25000.0
        
        sim_result = await asyncio.to_thread(
            quant_service.simulate_stock_breakout,
            req.stock_symbol,
            req.expected_move_pct,
            spot,
        )
        return {"success": True, "simulation": sim_result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation error: {str(e)}")

@router.get("/options/nifty-quant/simulate")
async def simulate_breakout_get(
    stock: str = Query("NSE:HDFCBANK-EQ", description="Stock symbol (e.g. NSE:HDFCBANK-EQ)"),
    move_pct: float = Query(2.0, description="Expected breakout move in percentage"),
):
    """GET endpoint for quick breakout simulation testing."""
    try:
        matrix = await asyncio.to_thread(quant_service.get_full_quant_matrix)
        spot = matrix.get("spot_price") or 25000.0
        
        sim_result = await asyncio.to_thread(
            quant_service.simulate_stock_breakout,
            stock,
            move_pct,
            spot,
        )
        return {"success": True, "simulation": sim_result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Simulation error: {str(e)}")
