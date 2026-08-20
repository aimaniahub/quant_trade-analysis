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
from app.services.market_cache import get_market_cache, make_key
from app.services.rate_limiter import get_fyers_limiter, is_rate_limit_error


# Default TTLs (seconds) — last-resort L1/L2 only. The symbol store is the book.
TTL_QUOTES = 15.0
TTL_SPOT = 15.0
TTL_OPTION_CHAIN = 90.0
TTL_HISTORY = 45.0
# 15m bar only changes once per bar; 900s is the harvest contract
TTL_HISTORY_15M = 900.0


class FyersMarketService:
    """Service for fetching market data from Fyers API."""
    
    def __init__(self):
        self.settings = get_settings()
        self.auth_service = get_auth_service()
        self.cache = get_market_cache()
    
    def _get_fyers(self) -> Optional[fyersModel.FyersModel]:
        """Get authenticated Fyers model."""
        return self.auth_service.get_fyers_model()

    def _invoke(self, api_name: str, fn):
        """Pace Fyers REST and trip cooldown on 429 / empty gateway bodies."""
        lim = get_fyers_limiter()
        lim.acquire_sync()
        try:
            resp = fn()
        except Exception as exc:
            if is_rate_limit_error(exc):
                lim.trip_limit(f"{api_name}: {str(exc)[:80]}")
            raise
        if isinstance(resp, dict):
            code = resp.get("code")
            msg = resp.get("message") or resp.get("error") or ""
            nested = resp.get("Error") or {}
            if isinstance(nested, dict):
                code = code if code is not None else nested.get("code")
                msg = msg or nested.get("message") or nested.get("error") or ""
            blob = f"{code} {msg} {resp}"
            if is_rate_limit_error(blob) or code == 429:
                lim.trip_limit(f"{api_name}: {msg or code}")
            elif resp.get("s") in ("ok", "OK") or resp.get("code") == 200:
                lim.clear_soft()
        return resp
    
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

        Readers serve the Redis symbol store when fresh. Only the harvest
        writer (or a hard-stale escape hatch) hits Fyers.
        """
        from app.services import symbol_store as store

        syms = list(symbols[:50])
        if not store.is_harvest_writer():
            spots = store.get_spots(syms)
            missing = []
            for s in syms:
                if s not in spots or not spots[s].get("ltp"):
                    missing.append(s)
                    continue
                if not store.is_fresh(s, "spot", store.quotes_ttl()):
                    age = store.age(s, "spot")
                    if age is None or age > store.stale_hard():
                        missing.append(s)
            if not missing:
                store.note_reader_hit("quotes", ",".join(syms[:3]))
                return store.quotes_response_from_spots(syms, spots)
            store.note_reader_miss("quotes", f"n={len(missing)}")

        key = make_key("quotes", sorted(syms))

        def _fetch():
            fyers = self._get_fyers()
            if not fyers:
                return {"success": False, "error": "Not authenticated", "data": []}
            try:
                symbols_str = ",".join(syms)
                response = self._invoke("quotes", lambda: fyers.quotes({"symbols": symbols_str}))
                if response.get("s") == "ok":
                    return {
                        "success": True,
                        "data": response.get("d", []),
                        "timestamp": datetime.now().isoformat(),
                    }
                return {
                    "success": False,
                    "error": response.get("message", "Failed to fetch quotes"),
                    "data": [],
                }
            except Exception as e:
                return {"success": False, "error": str(e), "data": []}

        result = self.cache.cached_call(key, TTL_QUOTES, _fetch)
        if result.get("success"):
            for item in result.get("data") or []:
                spot = store.spot_from_quote_item(item)
                if spot and spot.get("symbol"):
                    store.put_spot(spot["symbol"], spot)
        return result
    
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
        days: int = 30,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Get historical OHLCV data from Fyers.

        force_refresh=True always hits the API (escape hatch only).
        Readers serve the Redis symbol store (15m / D harvested; 60/240 derived).
        """
        from app.services import symbol_store as store

        res = str(resolution)
        ttl = TTL_HISTORY_15M if res in ("15", "5", "30") else TTL_HISTORY
        store_res = res
        if res.upper() in ("D", "1D", "DAY", "DAILY"):
            store_res = "D"

        if not force_refresh:
            min_bars = 1
            if store_res in ("15", "D", "60", "240"):
                cached = store.get_history(symbol, store_res, min_bars=min_bars, days=days)
                fresh = False
                if cached:
                    if store_res == "15":
                        fresh = store.is_fresh(symbol, "history.15", store.history_15_ttl())
                    elif store_res == "D":
                        fresh = store.is_fresh(symbol, "history.D")
                    else:
                        # derived from 15m
                        fresh = store.is_fresh(symbol, "history.15", store.history_15_ttl())
                    if fresh or (
                        not store.is_harvest_writer()
                        and (store.age(symbol, f"history.{store_res if store_res in ('15', 'D') else '15'}") or 0)
                        < store.stale_hard() * 20
                    ):
                        store.note_reader_hit(f"history.{store_res}", symbol)
                        return store.history_as_response(symbol, res, cached, days)
                if not store.is_harvest_writer() and not cached:
                    store.note_reader_miss(f"history.{store_res}", symbol)

        key = make_key("history", symbol, resolution, from_date, to_date, days)

        def _fetch():
            fyers = self._get_fyers()
            if not fyers:
                return {"success": False, "error": "Not authenticated", "candles": []}
            try:
                if to_date is None:
                    to_dt = datetime.now()
                else:
                    to_dt = datetime.strptime(to_date, "%Y-%m-%d")

                if from_date is None:
                    from_dt = to_dt - timedelta(days=days)
                else:
                    from_dt = datetime.strptime(from_date, "%Y-%m-%d")

                range_from = str(int(from_dt.timestamp()))
                range_to = str(int(to_dt.timestamp()))

                response = self._invoke("history", lambda: fyers.history({
                    "symbol": symbol,
                    "resolution": resolution,
                    "date_format": "0",
                    "range_from": range_from,
                    "range_to": range_to,
                    "cont_flag": "1",
                }))

                if response.get("s") == "ok":
                    candles = response.get("candles", [])
                    formatted = []
                    for c in candles:
                        formatted.append({
                            "timestamp": c[0],
                            "datetime": datetime.fromtimestamp(c[0]).isoformat(),
                            "open": c[1],
                            "high": c[2],
                            "low": c[3],
                            "close": c[4],
                            "volume": c[5],
                        })
                    return {
                        "success": True,
                        "symbol": symbol,
                        "resolution": resolution,
                        "candles": formatted,
                        "count": len(formatted),
                    }
                return {
                    "success": False,
                    "error": response.get("message", "Failed to fetch history"),
                    "candles": [],
                }
            except Exception as e:
                return {"success": False, "error": str(e), "candles": []}

        if force_refresh:
            value = _fetch()
        else:
            value = self.cache.cached_call(key, ttl, _fetch)

        if isinstance(value, dict) and value.get("success"):
            candles = value.get("candles") or []
            if store_res in ("15", "D") and candles:
                store.put_history(symbol, store_res, candles, days)
                if store_res == "D":
                    # stamp IST date so next reader treats D as fresh today
                    snap = store.get(symbol) or {}
                    hist = (snap.get("history") or {}).get("D") or {}
                    hist["ist_date"] = datetime.now().strftime("%Y-%m-%d")
                    store.put(symbol, {"history": {"D": hist}})
            if force_refresh:
                self.cache.set(key, value, ttl)
        return value

    def peek_historical_data(
        self,
        symbol: str,
        resolution: str = "15",
        days: int = 30,
    ) -> Optional[Dict[str, Any]]:
        """Return cached history only (no Fyers call). Used by shared-pool scanners."""
        from app.services import symbol_store as store

        stored = store.get_history(symbol, resolution, min_bars=1, days=days)
        if stored:
            return store.history_as_response(symbol, resolution, stored, days)
        key = make_key("history", symbol, resolution, None, None, days)
        hit = self.cache.get(key)
        if hit is None:
            # Try common day windows other strategies may have warmed
            for d in (8, 5, 10, 20, 25, 30, 45, 60):
                if d == days:
                    continue
                alt = self.cache.get(make_key("history", symbol, resolution, None, None, d))
                if alt is not None and (alt.get("candles") or []):
                    return alt
            return None
        return hit
    
    def get_option_chain(
        self,
        symbol: str,
        strike_count: int = 14,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Get option chain data for an index/stock.

        Store-first: if the harvest snapshot is wide enough and not stale,
        slice it. Never key the cache by strike_count.
        """
        from app.services import symbol_store as store

        want = int(strike_count or store.canonical_strike_count(symbol))
        stored = store.get_chain(symbol, want)
        if stored:
            width = store.chain_width(stored.get("chain") or [], stored.get("atm_strike"))
            fresh = store.is_fresh(symbol, "chain", store.oc_ttl())
            age = store.age(symbol, "chain") or 0
            if width >= want and fresh:
                store.note_reader_hit("chain", symbol)
                return stored
            if (
                width >= want
                and not store.is_harvest_writer()
                and age <= store.stale_hard()
            ):
                store.note_reader_hit("chain.stale", symbol)
                return stored

        if not store.is_harvest_writer():
            store.note_reader_miss("chain", symbol, extra=f"want={want}")
            # Hard-stale or missing: one escape-hatch Fyers fetch (flow click / first paint)

        fetch_width = max(want, store.canonical_strike_count(symbol))
        # Key WITHOUT strike_count — one chain per symbol
        key = make_key("oc", symbol)

        def _fetch():
            return self._get_option_chain_uncached(symbol, fetch_width)

        if force_refresh:
            self.cache.delete(key)
            result = _fetch()
        else:
            result = self.cache.cached_call(key, TTL_OPTION_CHAIN, _fetch)
        if result.get("success"):
            store.put_chain(symbol, result)
            sliced = store.get_chain(symbol, want)
            if sliced:
                return sliced
        return result

    def _get_option_chain_uncached(self, symbol: str, strike_count: int = 10) -> Dict[str, Any]:
        fyers = self._get_fyers()
        if not fyers:
            return {"error": "Not authenticated", "success": False, "chain": []}
        
        try:
            data = {
                "symbol": symbol,
                "strikecount": strike_count
            }
            response = self._invoke("optionchain", lambda: fyers.optionchain(data))
            
            if response.get("code") == 200 or response.get("s") == "ok":
                chain_data = response.get("data", {})
                
                # Extract raw options chain (flat list of CE/PE contracts)
                options_list = chain_data.get("optionsChain", [])
                expiry_data = chain_data.get("expiryData", [])
                
                # First item is usually the underlying spot data
                spot_price = None
                atm_strike = None

                # Derive time-to-expiry from nearest expiry date when available
                time_to_expiry = self._estimate_time_to_expiry(expiry_data)
                
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
    
    def _estimate_time_to_expiry(self, expiry_data: Any) -> float:
        """
        Estimate years to nearest expiry from Fyers expiryData payload.
        Falls back to ~7 calendar days if parsing fails.
        """
        default_tte = 7 / 365.0
        if not expiry_data:
            return default_tte

        try:
            first = expiry_data[0] if isinstance(expiry_data, list) else expiry_data
            raw = None
            if isinstance(first, dict):
                raw = (
                    first.get("date")
                    or first.get("expiry")
                    or first.get("expiry_date")
                    or first.get("Expiry")
                )
            elif first is not None:
                raw = str(first)

            if not raw:
                return default_tte

            # Support epoch seconds/ms or common date strings
            if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.isdigit()):
                ts = float(raw)
                if ts > 1e12:  # milliseconds
                    ts /= 1000.0
                expiry_dt = datetime.fromtimestamp(ts)
            else:
                raw_s = str(raw).strip()
                expiry_dt = None
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y", "%Y%m%d", "%d %b %Y"):
                    try:
                        expiry_dt = datetime.strptime(raw_s[:11].strip(), fmt)
                        break
                    except ValueError:
                        continue
                if expiry_dt is None:
                    # ISO-like
                    try:
                        expiry_dt = datetime.fromisoformat(raw_s.replace("Z", "+00:00")).replace(tzinfo=None)
                    except ValueError:
                        return default_tte

            # Treat expiry as end-of-day IST approx (use local naive for simplicity)
            now = datetime.now()
            days = max((expiry_dt.date() - now.date()).days, 0)
            # Use at least a few hours of theta on expiry day
            tte_years = max(days / 365.0, 0.5 / 365.0)
            return tte_years
        except Exception:
            return default_tte

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
            "NSE:FINNIFTY-INDEX",
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
        from app.services import symbol_store as store

        stored = store.get_spot(symbol)
        if stored and stored.get("ltp"):
            fresh = store.is_fresh(symbol, "spot", store.quotes_ttl())
            age = store.age(symbol, "spot") or 0
            if fresh or (not store.is_harvest_writer() and age <= store.stale_hard()):
                store.note_reader_hit("spot", symbol)
                return store.spot_response(symbol, stored)

        if not store.is_harvest_writer():
            store.note_reader_miss("spot", symbol)

        key = make_key("spot", symbol)

        def _fetch():
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
                }
            return {
                "success": False,
                "error": result.get("error", "No quote data"),
                "symbol": symbol,
            }

        hit = self.cache.get(key)
        if hit is not None:
            if isinstance(hit, dict):
                out = dict(hit)
                out["_cache"] = "hit"
                return out
            return hit
        value = _fetch()
        if value.get("success"):
            self.cache.set(key, value, TTL_SPOT)
            store.put_spot(symbol, value)
        if isinstance(value, dict):
            value = dict(value)
            value["_cache"] = "miss"
        return value


# Singleton instance
_market_service: Optional[FyersMarketService] = None


def get_market_service() -> FyersMarketService:
    """Get the market service instance."""
    global _market_service
    if _market_service is None:
        _market_service = FyersMarketService()
    return _market_service
