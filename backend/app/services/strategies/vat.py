"""
Value Adjustment Theory (VAT) Strategy
--------------------------------------
Implements the "Value Adjustment Theory" from the Berlin Manuscript.
Focuses on premium dislocation between equidistant strikes from spot price.
"""

from typing import List, Dict, Any, Optional, Tuple
from app.services.fyers_market import get_market_service

class ValueAdjustmentStrategy:
    def __init__(self):
        self.market_service = get_market_service()
        
        # Configuration
        self.NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"
        self.BANKNIFTY_SYMBOL = "NSE:NIFTYBANK-INDEX"
        
        # "Equidistant" strike scan range (from Spot)
        self.SCAN_RANGE_POINTS = {
            self.NIFTY_SYMBOL: 500,      # Scan up to 500 points away
            self.BANKNIFTY_SYMBOL: 1000  # Scan up to 1000 points away
        }
        
        # Step size for finding strikes
        self.STRIKE_STEP = {
            self.NIFTY_SYMBOL: 50,
            self.BANKNIFTY_SYMBOL: 100
        }
        
        # Minimum gap to consider per manuscript (e.g. ₹7 for Nifty)
        self.MIN_GAP_THRESHOLD = {
            self.NIFTY_SYMBOL: 7.0,
            self.BANKNIFTY_SYMBOL: 15.0 # Higher due to larger value
        }

    async def analyze_vat(self, symbol: str = "NSE:NIFTY50-INDEX") -> Dict[str, Any]:
        """
        Analyze the option chain for Value Adjustment opportunities.
        
        Args:
            symbol: Index symbol (default Nifty 50)
            
        Returns:
            Dict with analysis results, spot data, and signals.
        """
        # 1. Fetch Option Chain (Strike Count ~ 20-30 to cover scan range)
        # 500 points / 50 step = 10 strikes one side. So 20 totals. reliable count 30.
        strike_count = 30 
        
        # get_option_chain is sync in fyers_market.py, but we might wrap it or simple call it.
        # Looking at fyers_market.py, get_option_chain is a synchronous method (no async def).
        # But in FastAPI route we will likely run this in threadpool if it blocks, 
        # or just call it directly if it's fast enough. 
        # fyers_market.py uses 'fyers.optionchain(data)' which is likely blocking HTTP.
        # We will assume standard execution.
        
        chain_result = self.market_service.get_option_chain(symbol=symbol, strike_count=strike_count)
        
        if not chain_result.get("success"):
            return {
                "success": False, 
                "error": chain_result.get("error", "Failed to fetch chain")
            }
            
        spot_price = chain_result.get("spot_price")
        chain_data = chain_result.get("chain", [])
        
        if not spot_price or not chain_data:
            return {"success": False, "error": "No data available"}
            
        # 2. Convert chain list to a dictionary for O(1) lookup by strike
        chain_map = {item['strike_price']: item for item in chain_data}
        
        results = []
        strike_step = self.STRIKE_STEP.get(symbol, 50)
        scan_limit = self.SCAN_RANGE_POINTS.get(symbol, 500)
        min_gap = self.MIN_GAP_THRESHOLD.get(symbol, 7.0)
        
        # Round spot to nearest theoretical ATM (for reference anchor)
        # e.g., 25010 -> 25000.  25040 -> 25050 if Nifty.
        anchor_strike = round(spot_price / strike_step) * strike_step
        
        # 3. Iterate outwards finding equidistant pairs
        # We actually calculate exact distance from SPOT compared to strike.
        # Manuscript says: "Equidistant strikes from Spot". 
        # Since Spot is rarely exactly at a strike, we look for strikes that are symmetrically opposed
        # relative to the Anchor (ATM strike).
        
        # Example: Spot 25010. Anchor 25000.
        # Equidistant from Anchor: 25100 (OTM Call) vs 24900 (OTM Put).
        # Distance from Spot: 
        #   25100 - 25010 = 90 pts (Call distance)
        #   25010 - 24900 = 110 pts (Put distance)
        # This slight asymmetry (skew) is naturally priced in.
        # However, Berlin's simplified theory often compares strikes equidistant from the ROUNDED ATM.
        # Let's stick to the "Anchor Strike" method as it's the standard interpretation for straddles/strangles.
        
        for offset in range(strike_step, scan_limit + strike_step, strike_step):
            call_strike = anchor_strike + offset # OTM for Calls
            put_strike = anchor_strike - offset  # OTM for Puts
            
            call_data = chain_map.get(call_strike, {}).get("call")
            put_data = chain_map.get(put_strike, {}).get("put")
            
            if not call_data or not put_data:
                continue
                
            ce_ltp = call_data.get("ltp", 0)
            pe_ltp = put_data.get("ltp", 0)
            
            if ce_ltp == 0 or pe_ltp == 0: 
                continue
                
            # Calculate Gap
            gap = abs(ce_ltp - pe_ltp)
            avg_premium = (ce_ltp + pe_ltp) / 2
            gap_percentage = (gap / avg_premium * 100) if avg_premium > 0 else 0
            
            # Determine Undervalued Leg
            # Logic: If Call is 20 and Put is 10, Put is undervalued (assuming no massive trend bias justified)
            # The strategy buys the CHEAPER one, betting on mean reversion or "catch up".
            signal_type = "NONE"
            undervalued_strike = None
            undervalued_ltp = 0
            target_ltp = 0
            
            if gap >= min_gap:
                if ce_ltp < pe_ltp:
                    # Calls are cheaper. Buy CE.
                    signal_type = "BUY_CE"
                    undervalued_strike = call_strike
                    undervalued_ltp = ce_ltp
                    target_ltp = pe_ltp
                else:
                    # Puts are cheaper. Buy PE.
                    signal_type = "BUY_PE"
                    undervalued_strike = put_strike
                    undervalued_ltp = pe_ltp
                    target_ltp = ce_ltp
            
            results.append({
                "offset": offset,
                "call_strike": call_strike,
                "put_strike": put_strike,
                "ce_ltp": ce_ltp,
                "pe_ltp": pe_ltp,
                "gap": round(gap, 2),
                "is_opportunity": gap >= min_gap,
                "signal": signal_type,
                "undervalued_strike": undervalued_strike,
                "entry_price": undervalued_ltp,
                "theoretical_target": target_ltp
            })
            
        # 4. Filter for actionable signals
        opportunities = [r for r in results if r["is_opportunity"]]
        
        # Sort opportunities by Gap size (descending)
        opportunities.sort(key=lambda x: x["gap"], reverse=True)
        
        return {
            "success": True,
            "symbol": symbol,
            "spot_price": spot_price,
            "anchor_strike": anchor_strike,
            "total_opportunities": len(opportunities),
            "opportunities": opportunities,
            "full_analysis": results
        }

# Singleton
vat_strategy = ValueAdjustmentStrategy()

def get_vat_strategy():
    return vat_strategy
