"""
Fyers Market Data Service

Provides methods for fetching market data including quotes,
historical data, market depth, and option chain from Fyers API v3.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import pandas as pd

from fyers_apiv3 import fyersModel
import math

try:
    from scipy.stats import norm
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

from app.core.config import get_settings
from app.services.fyers_auth import get_auth_service


class FyersMarketService:
    """Service for fetching market data from Fyers API."""
    
    def __init__(self):
        self.settings = get_settings()
        self.auth_service = get_auth_service()
    
    def _get_fyers(self) -> Optional[fyersModel.FyersModel]:
        """Get authenticated Fyers model."""
        return self.auth_service.get_fyers_model()
    
    def _calculate_greeks(
        self,
        spot: float,
        strike: float,
        time_to_expiry: float,  # In years
        iv: float,  # Implied volatility as decimal
        option_type: str,  # "CE" or "PE"
        risk_free_rate: float = 0.07  # ~7% Indian RBI rate
    ) -> Dict[str, float]:
        """
        Calculate Greeks using Black-Scholes model.
        
        Returns:
            Dict with delta, gamma, theta, vega
        """
        if time_to_expiry <= 0 or iv <= 0 or spot <= 0 or strike <= 0:
            return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
        
        # Fallback if scipy is missing
        if not HAS_SCIPY:
            # Very basic linear approximation for Delta as a placeholder
            # ATM Delta ~0.5. More OTM -> smaller. More ITM -> larger.
            moneyness = (spot - strike) / (spot * iv * math.sqrt(time_to_expiry))
            if option_type == "CE":
                delta = 0.5 + 0.1 * moneyness
            else:
                delta = -0.5 + 0.1 * moneyness
            delta = max(-1.0, min(1.0, delta))
            
            return {
                "delta": round(delta, 4),
                "gamma": 0,
                "theta": 0,
                "vega": 0,
                "note": "Calculated using fallback (scipy missing)"
            }

        try:
            sqrt_t = math.sqrt(time_to_expiry)
            d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * iv ** 2) * time_to_expiry) / (iv * sqrt_t)
            d2 = d1 - iv * sqrt_t
            
            # Standard normal pdf and cdf
            pdf_d1 = norm.pdf(d1)
            cdf_d1 = norm.cdf(d1)
            cdf_d2 = norm.cdf(d2)
            cdf_neg_d1 = norm.cdf(-d1)
            cdf_neg_d2 = norm.cdf(-d2)
            
            # Greeks
            gamma = pdf_d1 / (spot * iv * sqrt_t)
            vega = spot * pdf_d1 * sqrt_t / 100  # Per 1% change in IV
            
            if option_type == "CE":
                delta = cdf_d1
                theta = (
                    -spot * pdf_d1 * iv / (2 * sqrt_t)
                    - risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * cdf_d2
                ) / 365  # Per day
            else:  # PE
                delta = cdf_d1 - 1
                theta = (
                    -spot * pdf_d1 * iv / (2 * sqrt_t)
                    + risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry) * cdf_neg_d2
                ) / 365
            
            return {
                "delta": round(delta, 4),
                "gamma": round(gamma, 6),
                "theta": round(theta, 2),
                "vega": round(vega, 2)
            }
        except Exception:
            return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
    
    def get_quotes(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Get real-time quotes for multiple symbols.
        
        Args:
            symbols: List of symbols (max 50), e.g., ["NSE:NIFTY50-INDEX", "NSE:SBIN-EQ"]
            
        Returns:
            Dict with quote data for each symbol
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"error": "Not authenticated", "data": []}
        
        try:
            # Fyers accepts comma-separated symbols
            symbols_str = ",".join(symbols[:50])  # Max 50 symbols
            data = {"symbols": symbols_str}
            response = fyers.quotes(data)
            
            if response.get("s") == "ok":
                return {
                    "success": True,
                    "data": response.get("d", []),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message", "Failed to fetch quotes"),
                    "data": []
                }
        except Exception as e:
            return {"success": False, "error": str(e), "data": []}
    
    def get_market_depth(self, symbol: str) -> Dict[str, Any]:
        """
        Get market depth (Level 2 data) for a symbol.
        
        Args:
            symbol: Symbol to get depth for, e.g., "NSE:SBIN-EQ"
            
        Returns:
            Dict with bid/ask levels
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"error": "Not authenticated"}
        
        try:
            data = {"symbol": symbol, "ohlcv_flag": "1"}
            response = fyers.depth(data)
            
            if response.get("s") == "ok":
                return {
                    "success": True,
                    "data": response.get("d", {}),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message", "Failed to fetch depth")
                }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_historical_data(
        self,
        symbol: str,
        resolution: str = "D",
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get historical OHLCV data.
        
        Args:
            symbol: Symbol e.g., "NSE:SBIN-EQ"
            resolution: Timeframe - "1", "5", "15", "30", "60", "D", "W", "M"
            from_date: Start date (YYYY-MM-DD) or None for auto
            to_date: End date (YYYY-MM-DD) or None for today
            days: Number of days back if from_date not specified
            
        Returns:
            Dict with OHLCV candles
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"error": "Not authenticated", "candles": []}
        
        try:
            # Calculate date range
            if to_date is None:
                to_dt = datetime.now()
            else:
                to_dt = datetime.strptime(to_date, "%Y-%m-%d")
            
            if from_date is None:
                from_dt = to_dt - timedelta(days=days)
            else:
                from_dt = datetime.strptime(from_date, "%Y-%m-%d")
            
            # Convert to epoch timestamps
            range_from = str(int(from_dt.timestamp()))
            range_to = str(int(to_dt.timestamp()))
            
            data = {
                "symbol": symbol,
                "resolution": resolution,
                "date_format": "0",  # 0 for epoch
                "range_from": range_from,
                "range_to": range_to,
                "cont_flag": "1"  # Continuous data
            }
            
            response = fyers.history(data)
            
            if response.get("s") == "ok":
                candles = response.get("candles", [])
                # Format: [timestamp, open, high, low, close, volume]
                formatted = []
                for c in candles:
                    formatted.append({
                        "timestamp": c[0],
                        "datetime": datetime.fromtimestamp(c[0]).isoformat(),
                        "open": c[1],
                        "high": c[2],
                        "low": c[3],
                        "close": c[4],
                        "volume": c[5]
                    })
                
                return {
                    "success": True,
                    "symbol": symbol,
                    "resolution": resolution,
                    "candles": formatted,
                    "count": len(formatted)
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message", "Failed to fetch history"),
                    "candles": []
                }
        except Exception as e:
            return {"success": False, "error": str(e), "candles": []}
    
    def get_option_chain(
        self,
        symbol: str,
        strike_count: int = 10
    ) -> Dict[str, Any]:
        """
        Get option chain data for an index/stock.
        
        Args:
            symbol: Underlying symbol e.g., "NSE:NIFTY50-INDEX" or "NSE:SBIN-EQ"
            strike_count: Number of strikes above/below ATM
            
        Returns:
            Dict with option chain data including OI, IV, Greeks
        """
        fyers = self._get_fyers()
        if not fyers:
            return {"error": "Not authenticated", "success": False, "chain": []}
        
        try:
            data = {
                "symbol": symbol,
                "strikecount": strike_count
            }
            response = fyers.optionchain(data)
            
            if response.get("code") == 200 or response.get("s") == "ok":
                chain_data = response.get("data", {})
                
                # Extract raw options chain (flat list of CE/PE contracts)
                options_list = chain_data.get("optionsChain", [])
                expiry_data = chain_data.get("expiryData", [])
                
                # First item is usually the underlying spot data
                spot_price = None
                atm_strike = None
                
                # Group by strike price and pair CE/PE
                strikes_dict = {}
                
                for opt in options_list:
                    strike = opt.get("strike_price")
                    opt_type = opt.get("option_type")
                    
                    # Skip non-option entries (like underlying index)
                    if strike == -1 or not opt_type:
                        # This is the underlying index data
                        if strike == -1:
                            spot_price = opt.get("ltp")
                        continue
                    
                    if strike not in strikes_dict:
                        strikes_dict[strike] = {
                            "strike_price": strike, 
                            "call": None, 
                            "put": None,
                            "call_greeks": None,
                            "put_greeks": None,
                            "call_oi": 0,
                            "put_oi": 0,
                            "call_iv": 0,
                            "put_iv": 0
                        }
                    
                    # Calculate time to expiry (estimate ~7 days for nearest expiry)
                    time_to_expiry = 7 / 365.0  # Default weekly expiry
                    iv_decimal = (opt.get("iv", 0) or 15) / 100  # Convert to decimal, default 15%
                    
                    # Calculate Greeks
                    greeks = self._calculate_greeks(
                        spot=spot_price or opt.get("ltp", 0),
                        strike=strike,
                        time_to_expiry=time_to_expiry,
                        iv=iv_decimal,
                        option_type=opt_type
                    )
                    
                    option_data = {
                        "symbol": opt.get("symbol"),
                        "ltp": opt.get("ltp"),
                        "oi": opt.get("oi", 0),
                        "oi_change": opt.get("oich", 0),
                        "oi_change_pct": opt.get("oichp", 0),
                        "volume": opt.get("volume", 0),
                        "iv": opt.get("iv"),
                        "bid": opt.get("bid"),
                        "ask": opt.get("ask"),
                        "chg": opt.get("ltpch", 0),
                        "chg_pct": opt.get("ltpchp", 0),
                        "prev_oi": opt.get("prev_oi", 0),
                        # Greeks
                        "delta": greeks["delta"],
                        "gamma": greeks["gamma"],
                        "theta": greeks["theta"],
                        "vega": greeks["vega"]
                    }
                    
                    if opt_type == "CE":
                        strikes_dict[strike]["call"] = option_data
                        strikes_dict[strike]["call_greeks"] = greeks
                        strikes_dict[strike]["call_oi"] = option_data["oi"]
                        strikes_dict[strike]["call_iv"] = option_data["iv"]
                    elif opt_type == "PE":
                        strikes_dict[strike]["put"] = option_data
                        strikes_dict[strike]["put_greeks"] = greeks
                        strikes_dict[strike]["put_oi"] = option_data["oi"]
                        strikes_dict[strike]["put_iv"] = option_data["iv"]
                
                # Sort by strike price and convert to list
                sorted_strikes = sorted(strikes_dict.keys())
                formatted_chain = [strikes_dict[s] for s in sorted_strikes]
                
                # Find ATM strike
                if spot_price and formatted_chain:
                    atm_strike = min(sorted_strikes, key=lambda x: abs(x - spot_price))
                
                return {
                    "success": True,
                    "symbol": symbol,
                    "spot_price": spot_price,
                    "atm_strike": atm_strike,
                    "total_call_oi": chain_data.get("callOi"),
                    "total_put_oi": chain_data.get("putOi"),
                    "pcr": round(chain_data.get("putOi", 0) / max(chain_data.get("callOi", 1), 1), 2),
                    "india_vix": chain_data.get("indiavixData", {}).get("ltp"),
                    "expiries": expiry_data,
                    "chain": formatted_chain,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                return {
                    "success": False,
                    "error": response.get("message", "Failed to fetch option chain"),
                    "chain": []
                }
        except Exception as e:
            return {"success": False, "error": str(e), "chain": []}
    
    def get_indices(self) -> Dict[str, Any]:
        """
        Get major market indices data.
        
        Returns:
            Dict with major indices (NIFTY, BANKNIFTY, etc.)
        """
        indices = [
            "NSE:NIFTY50-INDEX",
            "NSE:NIFTYBANK-INDEX",
            "NSE:NIFTYIT-INDEX",
            "NSE:NIFTYFIN-INDEX",
            "BSE:SENSEX-INDEX"
        ]
        
        return self.get_quotes(indices)
    
    def get_spot_price(self, symbol: str) -> Dict[str, Any]:
        """
        Get spot price for a single symbol.
        
        Args:
            symbol: Symbol to get price for
            
        Returns:
            Dict with spot price details
        """
        result = self.get_quotes([symbol])
        
        if result.get("success") and result.get("data"):
            quote = result["data"][0] if result["data"] else {}
            return {
                "success": True,
                "symbol": symbol,
                "ltp": quote.get("v", {}).get("lp"),
                "open": quote.get("v", {}).get("open_price"),
                "high": quote.get("v", {}).get("high_price"),
                "low": quote.get("v", {}).get("low_price"),
                "close": quote.get("v", {}).get("prev_close_price"),
                "change": quote.get("v", {}).get("ch"),
                "change_percent": quote.get("v", {}).get("chp"),
                "volume": quote.get("v", {}).get("volume"),
                "timestamp": datetime.now().isoformat()
            }
        else:
            return result


# Singleton instance
_market_service: Optional[FyersMarketService] = None


def get_market_service() -> FyersMarketService:
    """Get the market service instance."""
    global _market_service
    if _market_service is None:
        _market_service = FyersMarketService()
    return _market_service
