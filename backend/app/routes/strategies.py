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
    """
    strategy = get_vat_strategy()
    
    try:
        result = await strategy.analyze_vat(symbol)
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Analysis failed"))
            
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
