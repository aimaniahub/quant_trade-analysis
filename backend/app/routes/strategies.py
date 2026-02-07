from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from app.services.strategies.vat import get_vat_strategy

router = APIRouter(prefix="/strategies", tags=["Strategies"])

@router.get("/vat/scan")
async def scan_value_adjustment(
    symbol: str = Query("NSE:NIFTY50-INDEX", description="Symbol to scan (e.g. NSE:NIFTY50-INDEX)")
):
    """
    Scan for Value Adjustment Theory (VAT) opportunities.
    Returns premium dislocations between equidistant strikes.
    (Legacy endpoint with backward compatibility)
    """
    strategy = get_vat_strategy()
    
    try:
        result = await strategy.analyze_vat(symbol)
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Analysis failed"))
            
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vat/scan/advanced")
async def scan_vat_advanced(
    symbol: str = Query("NSE:NIFTY50-INDEX", description="Symbol to scan"),
    min_confidence: int = Query(0, ge=0, le=100, description="Minimum confidence score (0-100)"),
    include_greeks: bool = Query(True, description="Include Greeks in response"),
    max_signals: int = Query(10, ge=1, le=50, description="Maximum signals per category")
):
    """
    Advanced VAT scan with multi-parameter confidence scoring.
    
    Features:
    - Confidence score (0-100) based on gap, momentum, time, Greeks
    - Signals categorized as high/medium/low confidence
    - Trade parameters (SL, targets, risk-reward ratio)
    - Market context (expiry phase, momentum direction, VIX)
    """
    strategy = get_vat_strategy()
    
    try:
        result = await strategy.analyze_vat_advanced(
            symbol=symbol,
            min_confidence=min_confidence,
            include_greeks=include_greeks,
            max_signals=max_signals
        )
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Analysis failed"))
            
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vat/market-context")
async def get_market_context(
    symbol: str = Query("NSE:NIFTY50-INDEX", description="Symbol to get context for")
):
    """
    Get current market context for VAT trading decision.
    
    Returns:
    - Spot price and anchor strike
    - Expiry phase (ex-d2, ex-d1, ex-d0, regular)
    - Optimal trading window status
    - Momentum direction
    - VIX level
    """
    strategy = get_vat_strategy()
    
    try:
        context = await strategy.get_market_context(symbol)
        
        return {
            "success": True,
            "symbol": symbol,
            "context": {
                "spot_price": context.spot_price,
                "anchor_strike": context.anchor_strike,
                "expiry_phase": context.expiry_phase,
                "days_to_expiry": context.days_to_expiry,
                "current_time": context.current_time,
                "is_optimal_window": context.is_optimal_window,
                "momentum_direction": context.spot_momentum_direction,
                "vix": context.vix
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

