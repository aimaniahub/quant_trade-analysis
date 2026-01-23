"""
Nifty 50 Sentiment Analysis Service

Provides real-time market sentiment indicators:
- India VIX (fear gauge)
- Put-Call Ratio (PCR)
- Market Breadth (advances/declines)
- OI Change analysis
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from app.services.fyers_market import get_market_service
from app.services.fyers_auth import get_auth_service
from app.services.fno_stocks import FNO_STOCKS


class NiftySentimentService:
    """
    Nifty 50 Sentiment Analysis for institutional-grade dashboard.
    """
    
    def __init__(self):
        self.market_service = get_market_service()
        self.auth_service = get_auth_service()
        
        # Nifty index symbols
        self.nifty_symbol = "NSE:NIFTY50-INDEX"
        self.banknifty_symbol = "NSE:NIFTYBANK-INDEX"
        self.vix_symbol = "NSE:INDIAVIX-INDEX"
    
    def get_vix_data(self) -> Dict[str, Any]:
        """Get India VIX data with sentiment interpretation."""
        try:
            quote = self.market_service.get_spot_price(self.vix_symbol)
            if not quote.get("success"):
                return {"error": "Unable to fetch VIX", "value": None}
            
            vix_value = quote.get("ltp", 0) or 0
            prev_close = quote.get("prev_close", vix_value) or vix_value
            change = quote.get("change", 0) or 0
            change_pct = quote.get("change_pct", 0) or 0
            
            # Interpret VIX level
            if vix_value < 12:
                sentiment = "EXTREME_GREED"
                color = "green"
            elif vix_value < 15:
                sentiment = "LOW_FEAR"
                color = "green"
            elif vix_value < 20:
                sentiment = "NEUTRAL"
                color = "amber"
            elif vix_value < 25:
                sentiment = "ELEVATED_FEAR"
                color = "orange"
            else:
                sentiment = "EXTREME_FEAR"
                color = "red"
            
            return {
                "value": round(vix_value, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "trend": "up" if change > 0 else "down" if change < 0 else "flat",
                "sentiment": sentiment,
                "color": color,
                "message": f"VIX at {vix_value:.1f} - {sentiment.replace('_', ' ').title()}"
            }
        except Exception as e:
            return {"error": str(e), "value": None}
    
    def get_nifty_pcr(self) -> Dict[str, Any]:
        """Get Nifty 50 Put-Call Ratio from option chain."""
        try:
            chain_data = self.market_service.get_option_chain(self.nifty_symbol, strike_count=20)
            if not chain_data.get("success"):
                return {"error": "Unable to fetch Nifty OC", "pcr": None}
            
            pcr = chain_data.get("pcr") or 0
            total_call_oi = chain_data.get("total_call_oi") or 0
            total_put_oi = chain_data.get("total_put_oi") or 0
            
            # Interpret PCR
            if pcr < 0.7:
                sentiment = "BEARISH"
                color = "red"
                message = "Low PCR - Bearish bias / Potential traps"
            elif pcr < 0.9:
                sentiment = "MILDLY_BEARISH"
                color = "orange"
                message = "Below average PCR - Slight bearish tilt"
            elif pcr < 1.1:
                sentiment = "NEUTRAL"
                color = "amber"
                message = "Balanced PCR - Range-bound market"
            elif pcr < 1.3:
                sentiment = "MILDLY_BULLISH"
                color = "lime"
                message = "Above average PCR - Bullish lean"
            else:
                sentiment = "BULLISH"
                color = "green"
                message = "High PCR - Strong bullish sentiment"
            
            return {
                "pcr": round(pcr, 2),
                "total_call_oi": total_call_oi,
                "total_put_oi": total_put_oi,
                "sentiment": sentiment,
                "color": color,
                "message": message
            }
        except Exception as e:
            return {"error": str(e), "pcr": None}
    
    def get_market_breadth(self) -> Dict[str, Any]:
        """Calculate advances/declines for FNO stocks."""
        try:
            advances = 0
            declines = 0
            unchanged = 0
            errors = 0
            
            # Sample top 50 FNO stocks for breadth
            sample_stocks = FNO_STOCKS[:50]
            
            for symbol in sample_stocks:
                try:
                    quote = self.market_service.get_spot_price(symbol)
                    if quote.get("success"):
                        change = quote.get("change", 0) or 0
                        if change > 0:
                            advances += 1
                        elif change < 0:
                            declines += 1
                        else:
                            unchanged += 1
                    else:
                        errors += 1
                except:
                    errors += 1
            
            total = advances + declines + unchanged
            if total == 0:
                return {"error": "No data available", "advances": 0, "declines": 0}
            
            breadth_ratio = advances / (advances + declines) if (advances + declines) > 0 else 0.5
            
            if breadth_ratio > 0.7:
                sentiment = "STRONG_BULLISH"
                color = "green"
            elif breadth_ratio > 0.55:
                sentiment = "BULLISH"
                color = "lime"
            elif breadth_ratio > 0.45:
                sentiment = "NEUTRAL"
                color = "amber"
            elif breadth_ratio > 0.3:
                sentiment = "BEARISH"
                color = "orange"
            else:
                sentiment = "STRONG_BEARISH"
                color = "red"
            
            return {
                "advances": advances,
                "declines": declines,
                "unchanged": unchanged,
                "total": total,
                "ratio": round(breadth_ratio, 2),
                "sentiment": sentiment,
                "color": color,
                "message": f"{advances} advancing, {declines} declining"
            }
        except Exception as e:
            return {"error": str(e), "advances": 0, "declines": 0}
    
    def get_nifty_oi_change(self) -> Dict[str, Any]:
        """Get Nifty OI change analysis."""
        try:
            chain_data = self.market_service.get_option_chain(self.nifty_symbol, strike_count=15)
            if not chain_data.get("success"):
                return {"error": "Unable to fetch OC", "call_oi_change": 0, "put_oi_change": 0}
            
            chain = chain_data.get("chain", [])
            spot = chain_data.get("spot_price") or 0
            atm = chain_data.get("atm_strike") or 0
            
            # Aggregate OI change around ATM
            call_oi_change = 0
            put_oi_change = 0
            
            for strike_data in chain:
                strike = strike_data.get("strike_price", 0)
                # Focus on strikes within 2% of spot
                if spot and abs(strike - spot) / spot <= 0.02:
                    call = strike_data.get("call", {}) or {}
                    put = strike_data.get("put", {}) or {}
                    call_oi_change += call.get("oi_change", 0) or 0
                    put_oi_change += put.get("oi_change", 0) or 0
            
            # Interpret OI change
            net_change = put_oi_change - call_oi_change
            if net_change > 10000:
                sentiment = "BULLISH_BUILDUP"
                color = "green"
                message = "Put writers active - Bullish signal"
            elif net_change > 0:
                sentiment = "MILD_BULLISH"
                color = "lime"
                message = "Slight put OI addition"
            elif net_change > -10000:
                sentiment = "MILD_BEARISH"
                color = "orange"
                message = "Slight call OI addition"
            else:
                sentiment = "BEARISH_BUILDUP"
                color = "red"
                message = "Call writers active - Bearish signal"
            
            return {
                "call_oi_change": call_oi_change,
                "put_oi_change": put_oi_change,
                "net_change": net_change,
                "sentiment": sentiment,
                "color": color,
                "message": message
            }
        except Exception as e:
            return {"error": str(e), "call_oi_change": 0, "put_oi_change": 0}
    
    def get_nifty_levels(self) -> Dict[str, Any]:
        """Get current Nifty spot with support/resistance from OI."""
        try:
            chain_data = self.market_service.get_option_chain(self.nifty_symbol, strike_count=20)
            if not chain_data.get("success"):
                return {"error": "Unable to fetch OC"}
            
            spot = chain_data.get("spot_price") or 0
            
            # Find max OI strikes for support/resistance
            chain = chain_data.get("chain", [])
            max_call_oi = 0
            max_put_oi = 0
            resistance = 0
            support = 0
            
            for strike_data in chain:
                strike = strike_data.get("strike_price", 0)
                call_oi = strike_data.get("call_oi", 0) or 0
                put_oi = strike_data.get("put_oi", 0) or 0
                
                if strike > spot and call_oi > max_call_oi:
                    max_call_oi = call_oi
                    resistance = strike
                if strike < spot and put_oi > max_put_oi:
                    max_put_oi = put_oi
                    support = strike
            
            return {
                "spot": round(spot, 2),
                "support": support,
                "support_oi": max_put_oi,
                "resistance": resistance,
                "resistance_oi": max_call_oi,
                "range": f"{support} - {resistance}"
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_full_sentiment(self) -> Dict[str, Any]:
        """Get complete Nifty sentiment dashboard data."""
        return {
            "vix": self.get_vix_data(),
            "pcr": self.get_nifty_pcr(),
            "breadth": self.get_market_breadth(),
            "oi_change": self.get_nifty_oi_change(),
            "levels": self.get_nifty_levels(),
            "timestamp": datetime.now().isoformat()
        }


# Singleton instance
_sentiment_service: Optional[NiftySentimentService] = None


def get_sentiment_service() -> NiftySentimentService:
    """Get the sentiment service instance."""
    global _sentiment_service
    if _sentiment_service is None:
        _sentiment_service = NiftySentimentService()
    return _sentiment_service
