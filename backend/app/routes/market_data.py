from fastapi import APIRouter, HTTPException, Query, Body
from typing import Optional, List
from pydantic import BaseModel

from app.services.fyers_market import get_market_service
from app.services.fno_intelligence import get_intelligence_engine
from app.services.fno_stocks import get_fno_stocks, TOP_FNO_STOCKS
from app.services.high_volume_scanner import get_scanner_service

router = APIRouter()
market_service = get_market_service()
intelligence_engine = get_intelligence_engine()
scanner_service = get_scanner_service()


class BulkAnalysisRequest(BaseModel):
    """Request model for bulk option chain analysis"""
    symbols: List[str]


@router.get("/market/spot/{symbol}")
async def get_spot_price(symbol: str):
    """Get current spot price for a symbol."""
    result = market_service.get_spot_price(symbol)
    if result.get("success"):
        return result
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to fetch spot price"))


@router.get("/market/state")
async def get_market_state(symbol: str = Query("NSE:NIFTY50-INDEX", description="Symbol to analyze")):
    """
    Get market state analysis using the F&O Intelligence Engine.
    
    Returns:
        Market state classification (TREND, RANGE, ADJUSTMENT, NO-TRADE),
        confidence level, analysis details, and trading signals.
    """
    # Get fresh option chain data
    chain_data = market_service.get_option_chain(symbol, strike_count=10)
    
    if not chain_data.get("success"):
        raise HTTPException(status_code=400, detail=chain_data.get("error", "Failed to fetch option chain"))
    
    # Run intelligence analysis
    analysis = intelligence_engine.get_analysis_summary(chain_data)
    
    return analysis


@router.get("/market/stocks/scan")
async def scan_fno_stocks(
    limit: int = Query(20, ge=1, le=50, description="Maximum number of stocks to return"),
    tradable_only: bool = Query(False, description="Only return TREND/ADJUSTMENT stocks"),
    top_only: bool = Query(True, description="Scan only top 20 high-volume stocks")
):
    """
    Scan F&O stocks and return analysis using real market data.
    
    This endpoint analyzes F&O stocks based on real-time or last available prices 
    from the Fyers API. No mock data is used.
    
    Returns:
        List of stock analyses sorted by tradability and confidence.
    """
    from datetime import datetime
    
    # Get stock list
    stocks = TOP_FNO_STOCKS if top_only else get_fno_stocks()[:limit]
    
    results = []
    errors = []
    
    for symbol in stocks[:limit]:
        try:
            # Always fetch real chain data from Fyers
            # Fyers provides LTP and OI even when the market is closed
            chain_data = market_service.get_option_chain(symbol, strike_count=5)
            
            if chain_data.get("success"):
                # Analyze using real data, skipping time restrictions for scanning
                analysis = intelligence_engine.analyze_stock(symbol, chain_data)
                
                if "error" not in analysis:
                    results.append(analysis)
                else:
                    errors.append({"symbol": symbol, "error": analysis.get("error")})
            else:
                errors.append({
                    "symbol": symbol, 
                    "error": chain_data.get("error", "Failed to fetch real market data")
                })
                
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})
    
    # Sort by tradability (tradable first) and then by confidence
    results.sort(key=lambda x: (
        0 if x.get("tradable") else 1,
        -(x.get("confidence") or 0)
    ))
    
    # Filter if tradable_only
    if tradable_only:
        results = [r for r in results if r.get("tradable")]
    
    # Limit results
    results = results[:limit]
    
    return {
        "success": True,
        "count": len(results),
        "total_scanned": len(stocks[:limit]),
        "tradable_count": sum(1 for r in results if r.get("tradable")),
        "stocks": results,
        "errors": errors if errors else None,
        "timestamp": datetime.now().isoformat()
    }


@router.get("/market/indices")
async def get_indices():
    """Get major market indices data."""
    result = market_service.get_indices()
    if result.get("success"):
        return result
    else:
        # Return graceful degradation
        return {"success": False, "data": [], "error": result.get("error")}


@router.get("/market/history/{symbol}")
async def get_history(
    symbol: str,
    resolution: str = "D",
    days: int = 30
):
    """Get historical OHLCV data."""
    result = market_service.get_historical_data(symbol, resolution, days=days)
    if result.get("success"):
        return result
    else:
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to fetch history"))


@router.get("/market/high-volume-scan")
async def scan_high_volume_stocks(
    timeframe: str = Query("15", description="Timeframe in minutes: 15 or 60"),
    top_count: int = Query(5, ge=1, le=20, description="Number of top stocks to return")
):
    """
    Scan all F&O stocks for high volume buying activity.
    
    This endpoint:
    1. Scans all 200+ FNO stocks for volume anomalies
    2. Calculates relative volume vs 20-period average
    3. Detects buying pressure (bullish price action)
    4. Returns top N stocks sorted by composite score
    
    Args:
        timeframe: "15" for 15-minute or "60" for 1-hour candles
        top_count: Number of top high-volume stocks to return
        
    Returns:
        Dict with total scanned, high volume count, and top stocks with metrics
    """
    import asyncio
    
    try:
        result = await scanner_service.scan_high_volume_stocks(
            timeframe=timeframe,
            top_count=top_count
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")


@router.get("/market/fno-stocks")
async def get_fno_stocks_list():
    """
    Get list of all F&O stocks with cap classification.
    
    Returns:
        List of all FNO stocks with symbol, name, and cap (LARGE_CAP/MID_CAP)
    """
    try:
        stocks = scanner_service.get_all_fno_stocks()
        return {
            "success": True,
            "count": len(stocks),
            "stocks": stocks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/market/bulk-oc-analysis")
async def bulk_option_chain_analysis(
    request: BulkAnalysisRequest
):
    """
    Perform deep option chain analysis for multiple stocks.
    
    This endpoint analyzes:
    - OI concentrations (support/resistance levels)
    - Breakout signals (day high breaks, IV skew)
    - Greeks analysis (delta clustering, gamma concentration)
    - Market state from Intelligence Engine
    
    Args:
        symbols: List of stock symbols to analyze (e.g., ["NSE:RELIANCE-EQ", "NSE:TCS-EQ"])
        
    Returns:
        Ranked list of stocks with composite scores and detailed reasons
    """
    import asyncio
    
    if not request.symbols:
        raise HTTPException(status_code=400, detail="No symbols provided")
    
    if len(request.symbols) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 symbols allowed per request")
    
    try:
        result = await scanner_service.bulk_option_chain_analysis(
            symbols=request.symbols
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/market/nifty-sentiment")
async def get_nifty_sentiment():
    """
    Get complete Nifty 50 sentiment dashboard data.
    
    Returns:
        VIX data, PCR analysis, market breadth, OI change, support/resistance levels
    """
    from app.services.nifty_sentiment import get_sentiment_service
    
    sentiment_service = get_sentiment_service()
    return sentiment_service.get_full_sentiment()


@router.get("/market/live-trade-signal/{symbol}")
async def get_live_trade_signal(symbol: str):
    """
    Get live trade signal for a specific symbol.
    
    Returns:
        Current trade recommendation with entry, stop-loss, target, and confidence
    """
    try:
        # Fetch fresh option chain
        chain_data = market_service.get_option_chain(symbol, strike_count=20)
        
        if not chain_data.get("success"):
            raise HTTPException(status_code=400, detail=chain_data.get("error", "Failed to fetch OC"))
        
        spot_price = chain_data.get("spot_price") or 0
        atm_strike = chain_data.get("atm_strike") or 0
        
        if not spot_price or spot_price <= 0:
            raise HTTPException(status_code=400, detail="No valid spot price")
        
        # Perform analysis
        oi_analysis = scanner_service._analyze_oi_concentrations(chain_data, spot_price)
        greeks_analysis = scanner_service._calculate_greeks_score(chain_data)
        intel_analysis = intelligence_engine.get_analysis_summary(chain_data, bypass_time_check=True)
        
        # Generate trade recommendation
        trade_rec = scanner_service._generate_trade_recommendation(
            symbol, spot_price, atm_strike,
            oi_analysis, greeks_analysis, intel_analysis
        )
        
        return {
            "symbol": symbol,
            "name": symbol.replace("NSE:", "").replace("-EQ", ""),
            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "oi_analysis": oi_analysis,
            "greeks_analysis": greeks_analysis,
            "intel_state": intel_analysis.get("state"),
            "tradable": intel_analysis.get("tradable"),
            "trade_recommendation": trade_rec,
            "timestamp": chain_data.get("timestamp")
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.get("/market/greeks-heatmap/{symbol}")
async def get_greeks_heatmap(
    symbol: str,
    strike_count: int = Query(15, ge=5, le=30, description="Number of strikes to include")
):
    """
    Get Greeks heatmap data for visualization.
    
    Returns:
        Strike-wise Delta, Gamma, Theta, Vega for both CE and PE
    """
    chain_data = market_service.get_option_chain(symbol, strike_count=strike_count)
    
    if not chain_data.get("success"):
        raise HTTPException(status_code=400, detail=chain_data.get("error", "Failed to fetch OC"))
    
    spot_price = chain_data.get("spot_price") or 0
    atm_strike = chain_data.get("atm_strike") or 0
    chain = chain_data.get("chain", [])
    
    heatmap_data = []
    for strike_data in chain:
        strike = strike_data.get("strike_price", 0)
        call = strike_data.get("call", {}) or {}
        put = strike_data.get("put", {}) or {}
        
        heatmap_data.append({
            "strike": strike,
            "is_atm": strike == atm_strike,
            "is_itm_ce": strike < spot_price,
            "is_itm_pe": strike > spot_price,
            "call_delta": call.get("delta") or 0,
            "call_gamma": call.get("gamma") or 0,
            "call_theta": call.get("theta") or 0,
            "call_vega": call.get("vega") or 0,
            "call_iv": call.get("iv") or 0,
            "call_oi": call.get("oi") or 0,
            "call_ltp": call.get("ltp") or 0,
            "put_delta": put.get("delta") or 0,
            "put_gamma": put.get("gamma") or 0,
            "put_theta": put.get("theta") or 0,
            "put_vega": put.get("vega") or 0,
            "put_iv": put.get("iv") or 0,
            "put_oi": put.get("oi") or 0,
            "put_ltp": put.get("ltp") or 0
        })
    
    # Find max gamma strike (key pivot point)
    max_gamma_strike = max(heatmap_data, key=lambda x: abs(x["call_gamma"]) + abs(x["put_gamma"]), default=None)
    
    return {
        "symbol": symbol,
        "spot_price": spot_price,
        "atm_strike": atm_strike,
        "max_gamma_strike": max_gamma_strike.get("strike") if max_gamma_strike else None,
        "heatmap": heatmap_data,
        "timestamp": chain_data.get("timestamp")
    }
