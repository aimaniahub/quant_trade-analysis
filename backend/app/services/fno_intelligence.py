"""
F&O Market Intelligence Engine

Core philosophy from fnoanalysis.md:
- "In F&O stocks, price lies. Futures show intent. Options reveal manipulation."
- Never predict price, interpret market behavior
- Identify premium traps, filter fake moves, align with institutions
"""

from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class MarketState(str, Enum):
    """Market state classifications"""
    TREND = "TREND"          # Directional move
    RANGE = "RANGE"          # Sideways
    INTENT = "INTENT"        # Institutional accumulation/build-up
    NO_TRADE = "NO-TRADE"    # Illiquid / noisy


class OIPattern(str, Enum):
    """OI + Price relationship patterns"""
    LONG_BUILDUP = "LONG_BUILDUP"      # Price ↑, OI ↑ = Bullish
    SHORT_BUILDUP = "SHORT_BUILDUP"    # Price ↓, OI ↑ = Bearish
    SHORT_COVERING = "SHORT_COVERING"  # Price ↑, OI ↓ = Weak bullish
    LONG_UNWINDING = "LONG_UNWINDING"  # Price ↓, OI ↓ = Weak bearish
    TRAPPED = "TRAPPED"                # Flat price, OI ↑ = Trapped positions
    EXIT = "EXIT"                      # Flat price, OI ↓ = Adjustment/exit
    NEUTRAL = "NEUTRAL"


class FNOIntelligenceEngine:
    """
    F&O Stock Analysis Engine
    Analyzes option chain, futures, and premium behavior
    """
    
    def __init__(self):
        self.time_windows = {
            "noise": (9, 15, 10, 30),  # 9:15 - 10:30
            "structure": (10, 30, 12, 30),  # 10:30 - 12:30
            "traps": (12, 30, 14, 30),  # 12:30 - 2:30
            "adjustment": (14, 30, 15, 20),  # 2:30 - 3:20
            "high_risk": (15, 20, 15, 30)  # Last 10 min
        }
    
    def get_current_time_window(self) -> str:
        """Get current market time window"""
        now = datetime.now()
        hour, minute = now.hour, now.minute
        current_mins = hour * 60 + minute
        
        if current_mins < 9 * 60 + 15:
            return "pre_market"
        elif current_mins < 10 * 60 + 30:
            return "noise"
        elif current_mins < 12 * 60 + 30:
            return "structure"
        elif current_mins < 14 * 60 + 30:
            return "traps"
        elif current_mins < 15 * 60 + 20:
            return "adjustment"
        elif current_mins < 15 * 60 + 30:
            return "high_risk"
        else:
            return "post_market"
    
    def analyze_option_chain(self, chain_data: Dict[str, Any], bypass_time_check: bool = False) -> Dict[str, Any]:
        """
        Analyze option chain for market intelligence
        
        Key analysis points from fnoanalysis.md:
        - ATM premium behavior (most important)
        - OI distribution and concentration
        - CE vs PE imbalance
        - Premium distortion detection
        
        Args:
            chain_data: Option chain data from Fyers API
            bypass_time_check: If True, skip time window restrictions (for stock scanning)
        """
        if not chain_data.get("success") or not chain_data.get("chain"):
            return {"error": "No chain data available"}
        
        chain = chain_data["chain"]
        spot_price = chain_data.get("spot_price") or 0
        atm_strike = chain_data.get("atm_strike") or 0
        pcr = chain_data.get("pcr") or 0
        india_vix = chain_data.get("india_vix") or 0
        total_call_oi = chain_data.get("total_call_oi") or 0
        total_put_oi = chain_data.get("total_put_oi") or 0
        
        # Validate spot_price to avoid division by zero
        if not spot_price or spot_price <= 0:
            return {"error": "No valid spot price available"}
        
        # Find ATM and nearby strikes
        atm_data = None
        nearby_strikes = []
        
        for strike_data in chain:
            strike = strike_data["strike_price"]
            if strike == atm_strike:
                atm_data = strike_data
            # Get strikes within 2% of spot
            if abs(strike - spot_price) / spot_price < 0.02:
                nearby_strikes.append(strike_data)
        
        # ====== INSTITUTIONAL FLOW ANALYSIS (DEEP INTENT) ======
        institutional_flow = self._analyze_institutional_flow(chain, spot_price)
        
        # ====== ATM ANALYSIS (MOST IMPORTANT) ======
        atm_analysis = self._analyze_atm_behavior(atm_data, spot_price)
        
        # ====== OI DISTRIBUTION ANALYSIS ======
        oi_analysis = self._analyze_oi_distribution(chain, spot_price)
        
        # ====== PCR ANALYSIS ======
        pcr_signal = self._interpret_pcr(pcr)
        
        # ====== MARKET STATE CLASSIFICATION ======
        market_state = self._classify_market_state(
            atm_analysis, oi_analysis, institutional_flow, pcr, india_vix, bypass_time_check
        )
        
        # ====== STRIKE GUIDANCE (BUY ONLY) ======
        strike_guidance = self._get_strike_guidance(chain, spot_price, market_state, institutional_flow)
        
        return {
            "symbol": chain_data.get("symbol"),
            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "market_state": market_state["state"],
            "intent_score": institutional_flow["intent_score"],
            "confidence": market_state["confidence"],
            "message": market_state["message"],
            "time_window": self.get_current_time_window(),
            "pcr": pcr,
            "pcr_signal": pcr_signal,
            "india_vix": india_vix,
            "atm_analysis": atm_analysis,
            "oi_analysis": oi_analysis,
            "institutional_flow": institutional_flow,
            "strike_guidance": strike_guidance,
            "total_call_oi": total_call_oi,
            "total_put_oi": total_put_oi,
            "tradable": market_state["state"] in [MarketState.TREND.value, MarketState.INTENT.value],
            "timestamp": datetime.now().isoformat()
        }
    
    def _analyze_atm_behavior(self, atm_data: Optional[Dict], spot_price: float) -> Dict[str, Any]:
        """
        ATM is where:
        - Institutions hedge
        - Gamma is highest
        - Adjustments happen first
        """
        if not atm_data:
            return {"status": "NO_DATA"}
        
        call = atm_data.get("call") or {}
        put = atm_data.get("put") or {}
        
        call_ltp = call.get("ltp", 0) or 0
        put_ltp = put.get("ltp", 0) or 0
        call_oi = call.get("oi", 0) or 0
        put_oi = put.get("oi", 0) or 0
        call_chg = call.get("chg", 0) or 0
        put_chg = put.get("chg", 0) or 0
        
        # Greeks
        call_delta = call.get("delta", 0) or 0
        put_delta = put.get("delta", 0) or 0
        call_gamma = call.get("gamma", 0) or 0
        put_gamma = put.get("gamma", 0) or 0
        call_iv = call.get("iv", 0) or 0
        put_iv = put.get("iv", 0) or 0
        
        # ATM premium ratio
        atm_premium_ratio = call_ltp / max(put_ltp, 0.01) if put_ltp else 0
        
        # ATM OI ratio
        atm_oi_ratio = call_oi / max(put_oi, 1)
        
        # Premium change behavior
        premium_behavior = "NEUTRAL"
        if call_chg > 0 and put_chg < 0:
            premium_behavior = "BULLISH_PRESSURE"
        elif call_chg < 0 and put_chg > 0:
            premium_behavior = "BEARISH_PRESSURE"
        elif call_chg < 0 and put_chg < 0:
            premium_behavior = "THETA_DECAY"
        elif abs(call_chg) > abs(put_chg) * 2 or abs(put_chg) > abs(call_chg) * 2:
            if call_chg == 0 and put_chg == 0:
                premium_behavior = "FLAT"
            else:
                premium_behavior = "DISTORTION"
        
        # Greeks interpretation
        delta_strength = "WEAK"
        if abs(call_delta) > 0.5 or abs(put_delta) > 0.5:
            delta_strength = "STRONG"  # Trending
        gamma_zone = "LOW"
        if (call_gamma + put_gamma) / 2 > 0.005:
            gamma_zone = "HIGH"  # Volatile moves expected
        
        return {
            "strike": atm_data["strike_price"],
            "call_ltp": call_ltp,
            "put_ltp": put_ltp,
            "call_oi": call_oi,
            "put_oi": put_oi,
            "call_chg": call_chg,
            "put_chg": put_chg,
            "premium_ratio": round(atm_premium_ratio, 2),
            "oi_ratio": round(atm_oi_ratio, 2),
            "premium_behavior": premium_behavior,
            # Greeks
            "call_delta": call_delta,
            "put_delta": put_delta,
            "call_gamma": call_gamma,
            "put_gamma": put_gamma,
            "call_iv": call_iv,
            "put_iv": put_iv,
            "delta_strength": delta_strength,
            "gamma_zone": gamma_zone
        }
    
    def _analyze_oi_distribution(self, chain: List[Dict], spot_price: float) -> Dict[str, Any]:
        """
        OI Distribution analysis:
        - Heavy OI at one strike = magnet
        - Sudden OI drop = position exit
        - OI build + flat price = manipulation
        """
        max_call_oi = 0
        max_put_oi = 0
        max_call_strike = 0
        max_put_strike = 0
        
        for strike_data in chain:
            call = strike_data.get("call") or {}
            put = strike_data.get("put") or {}
            strike = strike_data["strike_price"]
            
            call_oi = call.get("oi", 0) or 0
            put_oi = put.get("oi", 0) or 0
            
            if call_oi > max_call_oi:
                max_call_oi = call_oi
                max_call_strike = strike
            if put_oi > max_put_oi:
                max_put_oi = put_oi
                max_put_strike = strike
        
        # Resistance = max call OI strike
        # Support = max put OI strike
        range_width = (max_call_strike or 0) - (max_put_strike or 0)
        # Safely check if spot is in range (handle None/0 values)
        spot_in_range = False
        if max_put_strike and max_call_strike and spot_price:
            spot_in_range = max_put_strike <= spot_price <= max_call_strike
        
        return {
            "resistance": max_call_strike,
            "resistance_oi": max_call_oi,
            "support": max_put_strike,
            "support_oi": max_put_oi,
            "range_width": range_width,
            "spot_in_range": spot_in_range,
            "bias": "NEUTRAL" if spot_in_range else ("BULLISH" if spot_price > max_call_strike else "BEARISH")
        }
    
    def _interpret_pcr(self, pcr: float) -> str:
        """Interpret Put-Call Ratio"""
        if pcr < 0.5:
            return "EXTREME_BEARISH"  # Too many calls
        elif pcr < 0.7:
            return "BEARISH"
        elif pcr < 0.9:
            return "NEUTRAL"
        elif pcr < 1.2:
            return "BULLISH"
        elif pcr < 1.5:
            return "STRONG_BULLISH"
        else:
            return "EXTREME_BULLISH"  # Contrarian - may reverse
    
    def _analyze_institutional_flow(self, chain: List[Dict], spot_price: float) -> Dict[str, Any]:
        """
        Detect 'Big Money' intent using Volume/OI ratios and Clustering.
        Expert Logic: When Volume > OI, positions are being aggressively initiated/closed.
        """
        clusters = []
        total_intent_score = 0
        
        for strike_data in chain:
            strike = strike_data["strike_price"]
            call = strike_data.get("call") or {}
            put = strike_data.get("put") or {}
            
            # Analyze Call Intent
            call_vol = call.get("volume", 0) or 0
            call_oi = call.get("oi", 0) or 1
            call_v_oi_ratio = call_vol / call_oi
            
            # Analyze Put Intent
            put_vol = put.get("volume", 0) or 0
            put_oi = put.get("oi", 0) or 1
            put_v_oi_ratio = put_vol / put_oi
            
            # Institutional Cluster Detection (High volume at whole numbers)
            is_whole_number = strike % 100 == 0 or strike % 50 == 0
            
            if call_v_oi_ratio > 1.5 or (is_whole_number and call_vol > 50000):
                clusters.append({
                    "strike": strike,
                    "type": "CALL_ACCUMULATION",
                    "strength": round(call_v_oi_ratio, 2),
                    "is_institutional": is_whole_number
                })
                total_intent_score += 10
                
            if put_v_oi_ratio > 1.5 or (is_whole_number and put_vol > 50000):
                clusters.append({
                    "strike": strike,
                    "type": "PUT_ACCUMULATION",
                    "strength": round(put_v_oi_ratio, 2),
                    "is_institutional": is_whole_number
                })
                total_intent_score += 10

        return {
            "intent_score": min(total_intent_score, 100),
            "clusters": clusters[:5],  # Top 5 most relevant clusters
            "big_money_present": any(c["is_institutional"] for c in clusters)
        }

    
    def _classify_market_state(
        self,
        atm_analysis: Dict,
        oi_analysis: Dict,
        institutional_flow: Dict,
        pcr: float,
        vix: float,
        bypass_time_check: bool = False
    ) -> Dict[str, Any]:
        """
        Classify market into: TREND, RANGE, ADJUSTMENT, NO-TRADE
        Only TREND and ADJUSTMENT allow trades
        
        Args:
            bypass_time_check: If True, skip time window restrictions
        """
        time_window = self.get_current_time_window()
        
        # Time-based restrictions (skip if bypass_time_check is True)
        if not bypass_time_check:
            # Market closed
            if time_window in ["pre_market", "post_market"]:
                return {
                    "state": MarketState.NO_TRADE.value,
                    "confidence": 100,
                    "message": "Market is closed"
                }
            
            # High risk window
            if time_window == "high_risk":
                return {
                    "state": MarketState.NO_TRADE.value,
                    "confidence": 90,
                    "message": "Last 10 minutes - High risk zone"
                }
            
            # Noise window
            if time_window == "noise":
                return {
                    "state": MarketState.NO_TRADE.value,
                    "confidence": 70,
                    "message": "Opening hour noise - Wait for structure"
                }
        
        # Intent detection (Big Money active)
        if institutional_flow.get("intent_score", 0) > 40:
            return {
                "state": MarketState.INTENT.value,
                "confidence": institutional_flow["intent_score"],
                "message": "Institutional intent detected via Volume clusters"
            }
        
        # Range detection
        if oi_analysis.get("spot_in_range"):
            range_width_pct = oi_analysis.get("range_width", 0) / max(oi_analysis.get("support", 1), 1) * 100
            if range_width_pct < 2:
                return {
                    "state": MarketState.RANGE.value,
                    "confidence": 80,
                    "message": f"Tight range between {oi_analysis['support']}-{oi_analysis['resistance']}"
                }
        
        # Trend detection based on ATM behavior
        atm_behavior = atm_analysis.get("premium_behavior", "NEUTRAL")
        if atm_behavior in ["BULLISH_PRESSURE", "BEARISH_PRESSURE"]:
            return {
                "state": MarketState.TREND.value,
                "confidence": 65,
                "message": f"Directional pressure detected: {atm_behavior}"
            }
        
        # Default to adjustment window if in that time
        if time_window == "adjustment":
            return {
                "state": MarketState.ADJUSTMENT.value,
                "confidence": 60,
                "message": "Adjustment time window (2:30-3:15 PM) - Watch ATM premiums"
            }
        
        # Structure building
        if time_window == "structure":
            return {
                "state": MarketState.RANGE.value,
                "confidence": 55,
                "message": "Structure building phase - Monitor OI concentration"
            }
        
        # Traps window
        if time_window == "traps":
            return {
                "state": MarketState.NO_TRADE.value,
                "confidence": 60,
                "message": "Trap zone (12:30-2:30 PM) - Wait for clarity"
            }
        
        return {
            "state": MarketState.RANGE.value,
            "confidence": 50,
            "message": "Neutral market - No clear signal"
        }
    
    def _get_strike_guidance(
        self,
        chain: List[Dict],
        spot_price: float,
        market_state: Dict,
        institutional_flow: Dict
    ) -> Dict[str, Any]:
        """
        Expert Logic: Provide precise ITM/ATM/OTM buy picks based on intent.
        No selling allowed.
        """
        if market_state["state"] == MarketState.NO_TRADE:
            return {"suggested": False}

        # Identify Trend Bias
        clusters = institutional_flow.get("clusters", [])
        call_intent = sum(1 for c in clusters if c["type"] == "CALL_ACCUMULATION")
        put_intent = sum(1 for c in clusters if c["type"] == "PUT_ACCUMULATION")
        
        bias = "BULLISH" if call_intent > put_intent else ("BEARISH" if put_intent > call_intent else "NEUTRAL")
        
        # Calculate ATM strike
        strike_interval = 50 if spot_price > 500 else 10
        atm_strike = round(spot_price / strike_interval) * strike_interval
        
        trades = []
        if bias == "BULLISH":
            trades.append({
                "type": "ITM_BUY",
                "strike": atm_strike - strike_interval,
                "instrument": "CE",
                "rationale": "Deep intent CALL accumulation detected"
            })
            trades.append({
                "type": "ATM_BUY",
                "strike": atm_strike,
                "instrument": "CE",
                "rationale": "Capitalize on immediate theta/delta alignment"
            })
        elif bias == "BEARISH":
            trades.append({
                "type": "ITM_BUY",
                "strike": atm_strike + strike_interval,
                "instrument": "PE",
                "rationale": "High-confidence PUT writing / accumulation by Big Money"
            })
            trades.append({
                "type": "ATM_BUY",
                "strike": atm_strike,
                "instrument": "PE",
                "rationale": "Direct bearish directional play"
            })

        return {
            "suggested": len(trades) > 0,
            "bias": bias,
            "trades": trades,
            "expert_note": f"Institutional clusters detected at {len(clusters)} strikes. Intent score: {institutional_flow['intent_score']}%"
        }

    
    def get_analysis_summary(self, chain_data: Dict[str, Any], bypass_time_check: bool = False) -> Dict[str, Any]:
        """
        Generate a summary suitable for UI display
        
        Format from fnoanalysis.md:
        STOCK: HDFCBANK
        STATE: ADJUSTMENT
        STRIKE: 930 CE
        REASON: ATM premium compression
        CONFIDENCE: 82%
        INVALIDATION: Spot > 945
        TIME WINDOW: 2:40–3:15 PM
        
        Args:
            chain_data: Option chain data from Fyers API
            bypass_time_check: If True, skip time window restrictions (for stock scanning)
        """
        analysis = self.analyze_option_chain(chain_data, bypass_time_check=bypass_time_check)
        
        if "error" in analysis:
            return analysis
        
        # Get key signals
        oi_analysis = analysis.get("oi_analysis", {})
        guidance = analysis.get("strike_guidance", {})
        institutional = analysis.get("institutional_flow", {})
        
        # Build alerts based on analysis
        alerts = []
        
        # Intent alert
        if institutional.get("big_money_present"):
            alerts.append({
                "type": "SIGNAL",
                "message": "Big Money Entry Detected at key strike levels"
            })
        
        # PCR alert
        pcr = analysis.get("pcr", 0)
        if pcr > 1.3:
            alerts.append({
                "type": "INFO",
                "message": f"High PCR ({pcr:.2f}) - Expert: Bullish intent buildup"
            })
        elif pcr < 0.6:
            alerts.append({
                "type": "WARNING",
                "message": f"Low PCR ({pcr:.2f}) - Expert: Bearish traps possible"
            })
        
        # VIX alert
        vix = analysis.get("india_vix", 0)
        if vix > 20:
            alerts.append({
                "type": "WARNING",
                "message": f"High VIX ({vix:.1f}) - Stick to ITM BUY only"
            })
        
        return {
            "symbol": analysis.get("symbol"),
            "spot_price": analysis.get("spot_price"),
            "atm_strike": analysis.get("atm_strike"),
            "state": analysis.get("market_state"),
            "intent_score": analysis.get("intent_score"),
            "confidence": analysis.get("confidence"),
            "message": analysis.get("message"),
            "time_window": analysis.get("time_window"),
            "tradable": analysis.get("tradable"),
            "pcr": analysis.get("pcr"),
            "vix": analysis.get("india_vix"),
            "support": oi_analysis.get("support"),
            "resistance": oi_analysis.get("resistance"),
            "strike_guidance": guidance,
            "institutional_flow": institutional,
            "alerts": alerts,
            "timestamp": analysis.get("timestamp")
        }
    
    def analyze_stock(self, symbol: str, chain_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a single F&O stock using real market data.
        
        Args:
            symbol: Stock symbol
            chain_data: Real chain data fetched from Fyers API
            
        Returns:
            Analysis summary for the stock
        """
        return self.get_analysis_summary(chain_data, bypass_time_check=True)


# Singleton instance
_intelligence_engine: Optional[FNOIntelligenceEngine] = None


def get_intelligence_engine() -> FNOIntelligenceEngine:
    """Get the intelligence engine instance."""
    global _intelligence_engine
    if _intelligence_engine is None:
        _intelligence_engine = FNOIntelligenceEngine()
    return _intelligence_engine


