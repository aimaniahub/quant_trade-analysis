"""
High Volume FNO Scanner Service

Scans all F&O stocks for high volume buying activity and performs
deep option chain analysis for identifying trading opportunities.

Key Features:
- Volume scanning with 15min/1hr timeframes
- Relative volume calculation vs 20-period average
- Buying pressure detection (volume + price action)
- OI concentration analysis for support/resistance
- Breakout signal detection
- Greeks-enhanced scoring
"""

from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from enum import Enum
import asyncio

from app.services.fyers_market import get_market_service
from app.services.fno_stocks import FNO_STOCKS, TOP_FNO_STOCKS
from app.services.fno_intelligence import get_intelligence_engine


class StockCap(str, Enum):
    """Stock market cap classification"""
    LARGE_CAP = "LARGE_CAP"
    MID_CAP = "MID_CAP"


# Large cap FNO stocks (top by market cap)
LARGE_CAP_STOCKS = {
    "NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:HDFCBANK-EQ", "NSE:ICICIBANK-EQ",
    "NSE:INFY-EQ", "NSE:HINDUNILVR-EQ", "NSE:SBIN-EQ", "NSE:BHARTIARTL-EQ",
    "NSE:ITC-EQ", "NSE:KOTAKBANK-EQ", "NSE:LT-EQ", "NSE:AXISBANK-EQ",
    "NSE:BAJFINANCE-EQ", "NSE:ASIANPAINT-EQ", "NSE:MARUTI-EQ", "NSE:TITAN-EQ",
    "NSE:SUNPHARMA-EQ", "NSE:TATAMOTORS-EQ", "NSE:NTPC-EQ", "NSE:POWERGRID-EQ",
    "NSE:WIPRO-EQ", "NSE:HCLTECH-EQ", "NSE:ULTRACEMCO-EQ", "NSE:NESTLEIND-EQ",
    "NSE:TECHM-EQ", "NSE:TATASTEEL-EQ", "NSE:ADANIENT-EQ", "NSE:ADANIPORTS-EQ",
    "NSE:M&M-EQ", "NSE:BAJAJFINSV-EQ", "NSE:DRREDDY-EQ", "NSE:CIPLA-EQ",
    "NSE:GRASIM-EQ", "NSE:JSWSTEEL-EQ", "NSE:HINDALCO-EQ", "NSE:COALINDIA-EQ",
    "NSE:BRITANNIA-EQ", "NSE:DIVISLAB-EQ", "NSE:ONGC-EQ", "NSE:BPCL-EQ",
}


class HighVolumeScannerService:
    """
    High Volume FNO Stock Scanner with Option Chain Analysis
    
    Workflow:
    1. Scan all FNO stocks for volume anomalies (15min/1hr)
    2. Filter to top 5 high volume buying stocks
    3. Perform deep option chain analysis on filtered stocks
    4. Score and rank based on OI, Greeks, and breakout signals
    """
    
    def __init__(self):
        self.market_service = get_market_service()
        self.intelligence_engine = get_intelligence_engine()
    
    def classify_stock_cap(self, symbol: str) -> StockCap:
        """Classify stock as Large Cap or Mid Cap"""
        return StockCap.LARGE_CAP if symbol in LARGE_CAP_STOCKS else StockCap.MID_CAP
    
    def get_all_fno_stocks(self) -> List[Dict[str, Any]]:
        """Get all FNO stocks with their cap classification"""
        stocks = []
        for symbol in FNO_STOCKS:
            stocks.append({
                "symbol": symbol,
                "name": symbol.replace("NSE:", "").replace("-EQ", ""),
                "cap": self.classify_stock_cap(symbol).value
            })
        return stocks
    
    def _extract_candle_volume(self, candle) -> float:
        """Extract volume from candle (handles both dict and list formats)."""
        if isinstance(candle, dict):
            return candle.get("volume", 0)
        return candle[5] if len(candle) > 5 else 0
    
    def _extract_candle_ohlc(self, candle) -> tuple:
        """Extract OHLC from candle (handles both dict and list formats)."""
        if isinstance(candle, dict):
            return (
                candle.get("open", 0),
                candle.get("high", 0),
                candle.get("low", 0),
                candle.get("close", 0),
                candle.get("volume", 0)
            )
        return tuple(candle[1:6]) if len(candle) >= 6 else (0, 0, 0, 0, 0)
    
    def _calculate_relative_volume(
        self, 
        candles: List, 
        lookback: int = 20
    ) -> Dict[str, Any]:
        """
        Calculate relative volume compared to average.
        
        Args:
            candles: OHLCV data (list of dicts or lists)
            lookback: Number of periods for average calculation
            
        Returns:
            Dict with current volume, avg volume, relative volume ratio
        """
        if not candles or len(candles) < 2:
            return {"current_volume": 0, "avg_volume": 0, "relative_volume": 0}
        
        volumes = [self._extract_candle_volume(c) for c in candles]
        current_vol = volumes[-1] if volumes else 0
        
        # Calculate average of previous periods (excluding current)
        prev_volumes = volumes[:-1][-lookback:] if len(volumes) > 1 else []
        avg_vol = sum(prev_volumes) / len(prev_volumes) if prev_volumes else 1
        
        relative_vol = current_vol / avg_vol if avg_vol > 0 else 0
        
        return {
            "current_volume": current_vol,
            "avg_volume": round(avg_vol, 0),
            "relative_volume": round(relative_vol, 2)
        }
    
    def _detect_buying_pressure(self, candles: List) -> Dict[str, Any]:
        """
        Detect buying pressure based on price action.
        
        Buying pressure indicators:
        - Close > Open (bullish candle)
        - Close near high
        - Volume higher than average
        """
        if not candles or len(candles) < 1:
            return {"is_buying": False, "strength": 0, "pattern": "NEUTRAL"}
        
        last_candle = candles[-1]
        open_price, high, low, close, volume = self._extract_candle_ohlc(last_candle)
        
        # Bullish candle check
        is_bullish = close > open_price
        
        # Close near high (within 30% of range from high)
        candle_range = high - low if high > low else 1
        close_position = (close - low) / candle_range if candle_range > 0 else 0.5
        close_near_high = close_position > 0.7
        
        # Calculate buying strength (0-100)
        strength = 0
        if is_bullish:
            strength += 40
        if close_near_high:
            strength += 30
        strength += min(30, int(close_position * 30))
        
        # Determine pattern
        if is_bullish and close_near_high:
            pattern = "STRONG_BUYING"
        elif is_bullish:
            pattern = "BUYING"
        elif close_near_high:
            pattern = "ACCUMULATION"
        else:
            pattern = "NEUTRAL"
        
        return {
            "is_buying": is_bullish,
            "strength": strength,
            "pattern": pattern,
            "close_position": round(close_position, 2)
        }
    
    async def scan_high_volume_stocks(
        self,
        timeframe: str = "15",
        top_count: int = 5,
        progress_callback: callable = None
    ) -> Dict[str, Any]:
        """
        Scan all FNO stocks for high volume buying activity.
        
        Args:
            timeframe: "15" for 15min or "60" for 1hr
            top_count: Number of top stocks to return
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dict with scanned stocks, top high volume stocks, progress info
        """
        all_stocks = FNO_STOCKS
        total_stocks = len(all_stocks)
        scanned = 0
        results = []
        errors = []
        
        for symbol in all_stocks:
            try:
                scanned += 1
                
                # Fetch historical data
                history = self.market_service.get_historical_data(
                    symbol=symbol,
                    resolution=timeframe,
                    days=5  # Last 5 days of intraday data
                )
                
                if not history.get("success") or not history.get("candles"):
                    errors.append({"symbol": symbol, "error": "No data available"})
                    continue
                
                candles = history["candles"]
                
                # Calculate metrics
                volume_data = self._calculate_relative_volume(candles)
                buying_data = self._detect_buying_pressure(candles)
                
                # Get current price (handle both dict and list formats)
                last_candle = candles[-1]
                open_price, high, low, close, volume = self._extract_candle_ohlc(last_candle)
                current_price = close
                price_change = ((close - open_price) / open_price * 100) if open_price > 0 else 0
                
                # Calculate composite score
                volume_score = min(100, volume_data["relative_volume"] * 25)  # Max 100 at 4x volume
                buying_score = buying_data["strength"]
                composite_score = (volume_score * 0.6) + (buying_score * 0.4)
                
                # Filter: Only include if relative volume > 1.5 or has buying pressure
                if volume_data["relative_volume"] >= 1.5 or buying_data["is_buying"]:
                    results.append({
                        "symbol": symbol,
                        "name": symbol.replace("NSE:", "").replace("-EQ", ""),
                        "cap": self.classify_stock_cap(symbol).value,
                        "price": round(current_price, 2),
                        "price_change_pct": round(price_change, 2),
                        "volume": volume_data,
                        "buying_pressure": buying_data,
                        "composite_score": round(composite_score, 1)
                    })
                
                if progress_callback:
                    progress_callback(scanned, total_stocks)
                    
            except Exception as e:
                errors.append({"symbol": symbol, "error": f"{type(e).__name__}: {str(e)}"})
        
        # Sort by composite score and get top stocks
        results.sort(key=lambda x: x["composite_score"], reverse=True)
        top_stocks = results[:top_count]
        
        return {
            "success": True,
            "timeframe": f"{timeframe}min",
            "total_scanned": scanned,
            "high_volume_count": len(results),
            "top_stocks": top_stocks,
            "all_high_volume": results,  # Full list for reference
            "errors_count": len(errors),
            "errors": errors[:10] if errors else None,  # Include first 10 errors for debugging
            "timestamp": datetime.now().isoformat()
        }
    
    def _analyze_oi_concentrations(
        self,
        chain_data: Dict[str, Any],
        spot_price: float
    ) -> Dict[str, Any]:
        """
        Analyze OI concentrations to find support/resistance levels.
        
        High OI strikes act as:
        - Call OI concentration = Resistance
        - Put OI concentration = Support
        """
        if not chain_data.get("chain"):
            return {"support": None, "resistance": None, "concentrations": []}
        
        chain = chain_data["chain"]
        
        # Find max OI strikes
        max_call_oi = 0
        max_put_oi = 0
        resistance_strike = None
        support_strike = None
        
        concentrations = []
        
        for strike_data in chain:
            strike = strike_data.get("strike_price", 0)
            call_oi = strike_data.get("call_oi", 0)
            put_oi = strike_data.get("put_oi", 0)
            
            # Track concentrations near spot (within 5%)
            if abs(strike - spot_price) / spot_price <= 0.05:
                concentrations.append({
                    "strike": strike,
                    "call_oi": call_oi,
                    "put_oi": put_oi,
                    "total_oi": call_oi + put_oi,
                    "pcr": round(put_oi / call_oi, 2) if call_oi > 0 else 0
                })
            
            # Find max OI strikes above spot (resistance)
            if strike > spot_price and call_oi > max_call_oi:
                max_call_oi = call_oi
                resistance_strike = strike
            
            # Find max OI strikes below spot (support)
            if strike < spot_price and put_oi > max_put_oi:
                max_put_oi = put_oi
                support_strike = strike
        
        # Sort concentrations by total OI
        concentrations.sort(key=lambda x: x["total_oi"], reverse=True)
        
        return {
            "support": support_strike,
            "resistance": resistance_strike,
            "support_oi": max_put_oi,
            "resistance_oi": max_call_oi,
            "concentrations": concentrations[:5]  # Top 5 concentrations
        }
    
    def _detect_breakout_signals(
        self,
        chain_data: Dict[str, Any],
        spot_price: float,
        day_high: float = None
    ) -> Dict[str, Any]:
        """
        Detect breakout signals from option chain data.
        
        Signals:
        - Price near/above day high
        - ATM premium expansion
        - OI buildup at ATM (activity)
        """
        signals = []
        breakout_score = 0
        
        if not chain_data.get("chain"):
            return {"signals": signals, "breakout_score": 0}
        
        chain = chain_data["chain"]
        atm_strike = chain_data.get("atm_strike")
        
        # Find ATM data
        atm_data = None
        for strike_data in chain:
            if strike_data.get("strike_price") == atm_strike:
                atm_data = strike_data
                break
        
        if atm_data:
            call_oi = atm_data.get("call_oi") or 0
            put_oi = atm_data.get("put_oi") or 0
            call_iv = atm_data.get("call_iv") or 0
            put_iv = atm_data.get("put_iv") or 0
            
            # High ATM activity signal
            total_atm_oi = call_oi + put_oi
            if total_atm_oi > 100000:  # Significant OI at ATM
                signals.append({
                    "type": "HIGH_ATM_ACTIVITY",
                    "message": f"High OI at ATM {atm_strike}: {total_atm_oi:,}",
                    "strength": "STRONG"
                })
                breakout_score += 25
            
            # IV skew analysis
            if call_iv > 0 and put_iv > 0:
                iv_skew = (call_iv - put_iv) / put_iv if put_iv > 0 else 0
                if iv_skew > 0.1:  # Call IV higher - bullish expectation
                    signals.append({
                        "type": "BULLISH_IV_SKEW",
                        "message": f"Call IV premium: {iv_skew:.1%}",
                        "strength": "MODERATE"
                    })
                    breakout_score += 15
                elif iv_skew < -0.1:  # Put IV higher - bearish expectation
                    signals.append({
                        "type": "BEARISH_IV_SKEW",
                        "message": f"Put IV premium: {abs(iv_skew):.1%}",
                        "strength": "MODERATE"
                    })
        
        # Day high breakout check
        if day_high and spot_price >= day_high * 0.99:
            signals.append({
                "type": "NEAR_DAY_HIGH",
                "message": f"Price near day high: ₹{spot_price:.2f} vs ₹{day_high:.2f}",
                "strength": "STRONG"
            })
            breakout_score += 30
        
        return {
            "signals": signals,
            "breakout_score": min(100, breakout_score),
            "is_breakout": breakout_score >= 50
        }
    
    def _calculate_greeks_score(
        self,
        chain_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calculate Greeks-based score for the stock.
        
        Factors:
        - Delta clustering (institutional positioning)
        - Gamma concentration (potential for big moves)
        - Vega analysis (volatility expectations)
        """
        if not chain_data.get("chain"):
            return {"score": 0, "analysis": {}}
        
        chain = chain_data["chain"]
        
        total_call_delta = 0
        total_put_delta = 0
        max_gamma_strike = None
        max_gamma = 0
        
        for strike_data in chain:
            call_greeks = strike_data.get("call_greeks", {})
            put_greeks = strike_data.get("put_greeks", {})
            call_oi = strike_data.get("call_oi", 0)
            put_oi = strike_data.get("put_oi", 0)
            
            # Weighted delta by OI
            call_delta = call_greeks.get("delta", 0) * call_oi
            put_delta = put_greeks.get("delta", 0) * put_oi
            total_call_delta += call_delta
            total_put_delta += abs(put_delta)
            
            # Track max gamma
            call_gamma = call_greeks.get("gamma", 0)
            if call_gamma > max_gamma:
                max_gamma = call_gamma
                max_gamma_strike = strike_data.get("strike_price")
        
        # Delta imbalance score
        delta_ratio = total_call_delta / total_put_delta if total_put_delta > 0 else 1
        delta_score = min(50, abs(delta_ratio - 1) * 25)  # Score based on imbalance
        
        # Gamma concentration score
        gamma_score = min(50, max_gamma * 5000)  # Higher gamma = potential for moves
        
        total_score = delta_score + gamma_score
        
        return {
            "score": round(min(100, total_score), 1),
            "analysis": {
                "delta_ratio": round(delta_ratio, 2),
                "delta_bias": "BULLISH" if delta_ratio > 1.2 else "BEARISH" if delta_ratio < 0.8 else "NEUTRAL",
                "max_gamma_strike": max_gamma_strike,
                "max_gamma": round(max_gamma, 4)
            }
        }
    
    def _generate_trade_recommendation(
        self,
        symbol: str,
        spot_price: float,
        atm_strike: float,
        oi_analysis: Dict[str, Any],
        greeks_analysis: Dict[str, Any],
        intel_analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate actionable trade recommendation based on analysis.
        
        Returns:
            Dict with trade type (CE/PE), strike, entry, stop-loss, target
        """
        if not intel_analysis.get("tradable"):
            return {
                "action": "NO_TRADE",
                "reason": intel_analysis.get("message", "Market conditions not favorable")
            }
        
        delta_bias = greeks_analysis.get("analysis", {}).get("delta_bias", "NEUTRAL")
        support = oi_analysis.get("support")
        resistance = oi_analysis.get("resistance")
        
        # Determine trade direction based on delta bias and OI
        if delta_bias == "BULLISH" and support:
            # Buy CE near support
            strike = atm_strike  # ATM or slightly OTM
            option_type = "CE"
            entry_zone = f"Near ₹{spot_price:.0f}"
            stop_loss = support
            target = resistance if resistance else atm_strike * 1.02
            confidence = "HIGH" if greeks_analysis.get("score", 0) > 50 else "MEDIUM"
        elif delta_bias == "BEARISH" and resistance:
            # Buy PE near resistance
            strike = atm_strike
            option_type = "PE"
            entry_zone = f"Near ₹{spot_price:.0f}"
            stop_loss = resistance
            target = support if support else atm_strike * 0.98
            confidence = "HIGH" if greeks_analysis.get("score", 0) > 50 else "MEDIUM"
        else:
            # Neutral - suggest straddle or wait
            return {
                "action": "WAIT",
                "reason": "No clear directional bias",
                "suggestion": "Consider ATM straddle if expecting volatility"
            }
        
        return {
            "action": "BUY",
            "option_type": option_type,
            "strike": strike,
            "entry_zone": entry_zone,
            "stop_loss": stop_loss,
            "target": target,
            "confidence": confidence,
            "reason": f"{delta_bias} bias with strong OI {'support' if option_type == 'CE' else 'resistance'}"
        }
    
    async def bulk_option_chain_analysis(
        self,
        symbols: List[str],
        progress_callback: callable = None
    ) -> Dict[str, Any]:
        """
        Perform deep option chain analysis for multiple stocks.
        
        Args:
            symbols: List of stock symbols to analyze
            progress_callback: Optional callback for progress updates
            
        Returns:
            Dict with analyzed stocks, rankings, and detailed reasons
        """
        total = len(symbols)
        analyzed = 0
        results = []
        errors = []
        
        for symbol in symbols:
            try:
                analyzed += 1
                
                # Fetch option chain with 20 strikes for comprehensive analysis
                chain_data = self.market_service.get_option_chain(symbol, strike_count=20)
                
                if not chain_data.get("success"):
                    errors.append({"symbol": symbol, "error": chain_data.get("error", "Failed to fetch")})
                    continue
                
                spot_price = chain_data.get("spot_price") or 0
                
                # Skip if no valid spot price
                if not spot_price or spot_price <= 0:
                    errors.append({"symbol": symbol, "error": "No valid spot price available"})
                    continue
                
                # Get day high from spot data
                spot_data = self.market_service.get_spot_price(symbol)
                day_high = spot_data.get("day_high") if spot_data.get("success") else None
                
                # Perform analyses
                oi_analysis = self._analyze_oi_concentrations(chain_data, spot_price)
                breakout_analysis = self._detect_breakout_signals(chain_data, spot_price, day_high)
                greeks_analysis = self._calculate_greeks_score(chain_data)
                
                # Run intelligence engine analysis
                intel_analysis = self.intelligence_engine.get_analysis_summary(chain_data, bypass_time_check=True)
                
                # Calculate composite score
                oi_score = 25 if oi_analysis["support"] and oi_analysis["resistance"] else 10
                breakout_score = breakout_analysis["breakout_score"] * 0.3
                greeks_score = greeks_analysis["score"] * 0.2
                intel_score = (intel_analysis.get("confidence", 50)) * 0.25
                
                composite_score = oi_score + breakout_score + greeks_score + intel_score
                
                # Generate reasons
                reasons = []
                if oi_analysis["support"]:
                    reasons.append(f"Strong Put OI support at {oi_analysis['support']}")
                if oi_analysis["resistance"]:
                    reasons.append(f"Call OI resistance at {oi_analysis['resistance']}")
                for signal in breakout_analysis["signals"]:
                    reasons.append(signal["message"])
                if greeks_analysis["analysis"]["delta_bias"] != "NEUTRAL":
                    reasons.append(f"Delta bias: {greeks_analysis['analysis']['delta_bias']}")
                if intel_analysis.get("tradable"):
                    reasons.append(f"Market state: {intel_analysis.get('state')} - TRADABLE")
                
                results.append({
                    "symbol": symbol,
                    "name": symbol.replace("NSE:", "").replace("-EQ", ""),
                    "spot_price": spot_price,
                    "day_high": day_high,
                    "atm_strike": chain_data.get("atm_strike"),
                    "composite_score": round(composite_score, 1),
                    "oi_analysis": oi_analysis,
                    "breakout_analysis": breakout_analysis,
                    "greeks_analysis": greeks_analysis,
                    "intel_analysis": {
                        "state": intel_analysis.get("state"),
                        "tradable": intel_analysis.get("tradable"),
                        "confidence": intel_analysis.get("confidence"),
                        "message": intel_analysis.get("message")
                    },
                    "reasons": reasons,
                    "rank": 0,  # Will be set after sorting
                    "trade_recommendation": self._generate_trade_recommendation(
                        symbol, spot_price, chain_data.get("atm_strike", 0),
                        oi_analysis, greeks_analysis, intel_analysis
                    )
                })
                
                if progress_callback:
                    progress_callback(analyzed, total)
                    
            except Exception as e:
                errors.append({"symbol": symbol, "error": str(e)})
        
        # Sort by composite score and assign ranks
        results.sort(key=lambda x: x["composite_score"], reverse=True)
        for i, result in enumerate(results):
            result["rank"] = i + 1
        
        return {
            "success": True,
            "total_analyzed": analyzed,
            "results": results,
            "errors": errors if errors else None,
            "timestamp": datetime.now().isoformat()
        }


# Singleton instance
_scanner_service: Optional[HighVolumeScannerService] = None


def get_scanner_service() -> HighVolumeScannerService:
    """Get the scanner service instance."""
    global _scanner_service
    if _scanner_service is None:
        _scanner_service = HighVolumeScannerService()
    return _scanner_service
