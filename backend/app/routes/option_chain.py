import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.services.fyers_market import get_market_service
from app.services.fno_intelligence import get_intelligence_engine

router = APIRouter()
market_service = get_market_service()
intelligence_engine = get_intelligence_engine()


@router.get("/options/chain/{symbol}")
async def get_option_chain(
    symbol: str,
    strike_count: int = Query(10, description="Number of strikes above/below ATM")
):
    """Get option chain for a symbol.
    
    Args:
        symbol: The underlying symbol (e.g., NSE:NIFTY50-INDEX, NSE:NIFTYBANK-INDEX)
        strike_count: Number of strikes to include above/below ATM
    """
    result = await asyncio.to_thread(market_service.get_option_chain, symbol, strike_count)
    if result.get("success"):
        return result
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to fetch option chain"))


@router.get("/options/analysis/{symbol}")
async def analyze_option_structure(
    symbol: str,
    strike_count: int = Query(10, ge=1, le=30),
):
    """Analyze option structure using the F&O Intelligence Engine."""
    result = await asyncio.to_thread(market_service.get_option_chain, symbol, strike_count)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to fetch option chain"))

    analysis = await asyncio.to_thread(
        intelligence_engine.analyze_option_chain, result, True
    )
    if "error" in analysis:
        raise HTTPException(status_code=400, detail=analysis["error"])

    atm = analysis.get("atm_analysis") or {}
    oi = analysis.get("oi_analysis") or {}
    institutional = analysis.get("institutional_flow") or {}

    return {
        "symbol": symbol,
        "spot_price": analysis.get("spot_price"),
        "atm_strike": analysis.get("atm_strike"),
        "market_state": analysis.get("market_state"),
        "confidence": analysis.get("confidence"),
        "message": analysis.get("message"),
        "tradable": analysis.get("tradable"),
        "pcr": analysis.get("pcr"),
        "india_vix": analysis.get("india_vix"),
        "analysis": {
            "premium_behavior": atm.get("premium_behavior", "NEUTRAL"),
            "atm_analysis": atm,
            "oi_pattern": oi.get("pattern") or oi.get("bias") or "NEUTRAL",
            "oi_analysis": oi,
            "institutional_flow": institutional,
            "strike_guidance": analysis.get("strike_guidance"),
            "message": analysis.get("message") or "Intelligence analysis complete",
        },
        "anomalies": [],
        "timestamp": analysis.get("timestamp"),
    }


@router.get("/options/adjustments/{symbol}")
async def detect_adjustments(
    symbol: str,
    strike_count: int = Query(10, ge=1, le=30),
):
    """Detect adjustment / actionable trade setups from intelligence summary."""
    result = await asyncio.to_thread(market_service.get_option_chain, symbol, strike_count)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to fetch option chain"))

    summary = await asyncio.to_thread(
        intelligence_engine.get_analysis_summary, result, False
    )
    if "error" in summary:
        raise HTTPException(status_code=400, detail=summary["error"])

    adjustment = summary.get("adjustment") or {}
    setup = adjustment.get("trade_setup")
    adjustments = []
    if adjustment.get("detected") and setup:
        adjustments.append({
            "type": summary.get("state"),
            "action": setup.get("action"),
            "rationale": setup.get("rationale"),
            "strikes": setup.get("strikes") or [],
            "bias": setup.get("bias"),
            "confidence": adjustment.get("confidence"),
            "invalidation": setup.get("invalidation"),
            "conditions": adjustment.get("conditions") or [],
            "is_tradable": bool(summary.get("tradable")),
        })

    return {
        "symbol": symbol,
        "state": summary.get("state"),
        "spot_price": summary.get("spot_price"),
        "atm_strike": summary.get("atm_strike"),
        "adjustments": adjustments,
        "tradable_count": len(adjustments),
        "adjustment": adjustment,
        "message": summary.get("message") or (
            "Adjustment setup detected" if adjustments else "No adjustment setup detected"
        ),
        "timestamp": summary.get("timestamp"),
    }
