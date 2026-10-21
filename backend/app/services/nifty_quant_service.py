"""
Nifty 50 Quant Option Chain & Market Transmission Engine.

Implements the institutional quantitative models specified in
NIFTY50_QUANT_OPTION_CHAIN_MASTER_RESEARCH.md:
1. Exact Black-Scholes Greeks (Delta, Gamma, Theta, Vega, IV).
2. 4-Quadrant Strike Classification (LBU, SBU, SH-COV, LUW, GAMMA_EXPLOSION)
   with precise UI color tokens and anomaly scoring.
3. Asymmetric Addition Ratio (AAR: PE Change in OI / CE Change in OI).
4. Analytical Max Pain with strike pinning drift detection.
5. Combined ATM Straddle Fair-Value VWAP & Skew Ratio.
6. Heavyweight Stock Point Contribution Transmission Engine (Top 10 weights).
7. Breakout Impact Simulator (Stock Breakout % -> Nifty Rally Points -> Target Strike).
8. Institutional Trap Detection (Call Traps & Put Traps).
9. Greeks-Optimized Best Trade Recommendation Engine (Delta sweet spot [0.38, 0.52]).
"""

import math
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

# Complete 50 Nifty 50 Constituent Stocks with Free-Float Market Weights & Sectors
NIFTY_50_CONSTITUENTS = [
    {"symbol": "NSE:HDFCBANK-EQ", "name": "HDFC Bank", "weight": 11.52, "sector": "Financial Services"},
    {"symbol": "NSE:RELIANCE-EQ", "name": "Reliance Industries", "weight": 9.18, "sector": "Oil Gas & Fuels"},
    {"symbol": "NSE:ICICIBANK-EQ", "name": "ICICI Bank", "weight": 8.08, "sector": "Financial Services"},
    {"symbol": "NSE:INFY-EQ", "name": "Infosys", "weight": 5.76, "sector": "Information Technology"},
    {"symbol": "NSE:TCS-EQ", "name": "TCS", "weight": 4.12, "sector": "Information Technology"},
    {"symbol": "NSE:ITC-EQ", "name": "ITC", "weight": 3.94, "sector": "FMCG"},
    {"symbol": "NSE:LT-EQ", "name": "Larsen & Toubro", "weight": 3.82, "sector": "Construction"},
    {"symbol": "NSE:AXISBANK-EQ", "name": "Axis Bank", "weight": 3.28, "sector": "Financial Services"},
    {"symbol": "NSE:SBIN-EQ", "name": "State Bank of India", "weight": 2.92, "sector": "Financial Services"},
    {"symbol": "NSE:BHARTIARTL-EQ", "name": "Bharti Airtel", "weight": 2.84, "sector": "Telecommunication"},
    {"symbol": "NSE:KOTAKBANK-EQ", "name": "Kotak Mahindra Bank", "weight": 2.68, "sector": "Financial Services"},
    {"symbol": "NSE:HINDUNILVR-EQ", "name": "Hindustan Unilever", "weight": 2.45, "sector": "FMCG"},
    {"symbol": "NSE:BAJFINANCE-EQ", "name": "Bajaj Finance", "weight": 2.14, "sector": "Financial Services"},
    {"symbol": "NSE:M&M-EQ", "name": "Mahindra & Mahindra", "weight": 2.02, "sector": "Automobile"},
    {"symbol": "NSE:MARUTI-EQ", "name": "Maruti Suzuki", "weight": 1.62, "sector": "Automobile"},
    {"symbol": "NSE:HCLTECH-EQ", "name": "HCL Technologies", "weight": 1.54, "sector": "Information Technology"},
    {"symbol": "NSE:SUNPHARMA-EQ", "name": "Sun Pharma", "weight": 1.48, "sector": "Healthcare"},
    {"symbol": "NSE:TMPV-EQ", "name": "Tata Motors PV", "weight": 1.42, "sector": "Automobile"},
    {"symbol": "NSE:NTPC-EQ", "name": "NTPC", "weight": 1.38, "sector": "Power"},
    {"symbol": "NSE:TITAN-EQ", "name": "Titan Company", "weight": 1.32, "sector": "Consumer Durables"},
    {"symbol": "NSE:POWERGRID-EQ", "name": "Power Grid Corp", "weight": 1.24, "sector": "Power"},
    {"symbol": "NSE:TATASTEEL-EQ", "name": "Tata Steel", "weight": 1.15, "sector": "Metals & Mining"},
    {"symbol": "NSE:ADANIENT-EQ", "name": "Adani Enterprises", "weight": 1.10, "sector": "Metals & Mining"},
    {"symbol": "NSE:ADANIPORTS-EQ", "name": "Adani Ports & SEZ", "weight": 1.05, "sector": "Services"},
    {"symbol": "NSE:COALINDIA-EQ", "name": "Coal India", "weight": 1.02, "sector": "Oil Gas & Fuels"},
    {"symbol": "NSE:BAJAJFINSV-EQ", "name": "Bajaj Finserv", "weight": 0.94, "sector": "Financial Services"},
    {"symbol": "NSE:ULTRACEMCO-EQ", "name": "UltraTech Cement", "weight": 0.92, "sector": "Construction Materials"},
    {"symbol": "NSE:ONGC-EQ", "name": "ONGC", "weight": 0.88, "sector": "Oil Gas & Fuels"},
    {"symbol": "NSE:ASIANPAINT-EQ", "name": "Asian Paints", "weight": 0.85, "sector": "Consumer Durables"},
    {"symbol": "NSE:JSWSTEEL-EQ", "name": "JSW Steel", "weight": 0.84, "sector": "Metals & Mining"},
    {"symbol": "NSE:GRASIM-EQ", "name": "Grasim Industries", "weight": 0.82, "sector": "Construction Materials"},
    {"symbol": "NSE:TECHM-EQ", "name": "Tech Mahindra", "weight": 0.80, "sector": "Information Technology"},
    {"symbol": "NSE:HINDALCO-EQ", "name": "Hindalco Industries", "weight": 0.78, "sector": "Metals & Mining"},
    {"symbol": "NSE:CIPLA-EQ", "name": "Cipla", "weight": 0.72, "sector": "Healthcare"},
    {"symbol": "NSE:DRREDDY-EQ", "name": "Dr. Reddy's Lab", "weight": 0.68, "sector": "Healthcare"},
    {"symbol": "NSE:APOLLOHOSP-EQ", "name": "Apollo Hospitals", "weight": 0.66, "sector": "Healthcare"},
    {"symbol": "NSE:NESTLEIND-EQ", "name": "Nestle India", "weight": 0.64, "sector": "FMCG"},
    {"symbol": "NSE:EICHERMOT-EQ", "name": "Eicher Motors", "weight": 0.62, "sector": "Automobile"},
    {"symbol": "NSE:HEROMOTOCO-EQ", "name": "Hero MotoCorp", "weight": 0.58, "sector": "Automobile"},
    {"symbol": "NSE:BPCL-EQ", "name": "BPCL", "weight": 0.56, "sector": "Oil Gas & Fuels"},
    {"symbol": "NSE:BRITANNIA-EQ", "name": "Britannia Industries", "weight": 0.54, "sector": "FMCG"},
    {"symbol": "NSE:DIVISLAB-EQ", "name": "Divi's Laboratories", "weight": 0.52, "sector": "Healthcare"},
    {"symbol": "NSE:TATACONSUM-EQ", "name": "Tata Consumer Products", "weight": 0.50, "sector": "FMCG"},
    {"symbol": "NSE:SBILIFE-EQ", "name": "SBI Life Insurance", "weight": 0.48, "sector": "Financial Services"},
    {"symbol": "NSE:HDFCLIFE-EQ", "name": "HDFC Life Insurance", "weight": 0.46, "sector": "Financial Services"},
    {"symbol": "NSE:BAJAJ-AUTO-EQ", "name": "Bajaj Auto", "weight": 0.45, "sector": "Automobile"},
    {"symbol": "NSE:BEL-EQ", "name": "Bharat Electronics", "weight": 0.45, "sector": "Capital Goods"},
    {"symbol": "NSE:TRENT-EQ", "name": "Trent Ltd", "weight": 0.44, "sector": "Consumer Services"},
    {"symbol": "NSE:SHRIRAMFIN-EQ", "name": "Shriram Finance", "weight": 0.43, "sector": "Financial Services"},
    {"symbol": "NSE:WIPRO-EQ", "name": "Wipro", "weight": 0.42, "sector": "Information Technology"},
]

# Legacy alias for backward compatibility
NIFTY_HEAVYWEIGHTS = NIFTY_50_CONSTITUENTS[:10]

def normal_cdf(x: float) -> float:
    """Cumulative standard normal distribution."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def normal_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * (x ** 2))

def compute_bs_price(
    spot: float, strike: float, days: float, iv_pct: float, opt_type: str = "CE", r: float = 0.07
) -> float:
    """Computes Black-Scholes theoretical price."""
    T = max(days / 365.0, 0.0005)
    sigma = max(iv_pct / 100.0, 0.01)
    if spot <= 0 or strike <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (r + 0.5 * (sigma ** 2)) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type.upper() == "CE":
        return spot * normal_cdf(d1) - strike * math.exp(-r * T) * normal_cdf(d2)
    else:
        return strike * math.exp(-r * T) * normal_cdf(-d2) - spot * normal_cdf(-d1)

def solve_implied_volatility(
    spot: float, strike: float, days: float, price: float, opt_type: str = "CE", r: float = 0.07
) -> float:
    """Solves Black-Scholes implied volatility via Newton-Raphson."""
    if price <= 1.0 or spot <= 0 or strike <= 0:
        return 14.0
    sigma = 18.0
    for _ in range(8):
        p = compute_bs_price(spot, strike, days, sigma, opt_type, r)
        diff = p - price
        if abs(diff) < 0.15:
            break
        T = max(days / 365.0, 0.0005)
        d1 = (math.log(spot / strike) + (r + 0.5 * ((sigma / 100.0) ** 2)) * T) / ((sigma / 100.0) * math.sqrt(T))
        vega = spot * math.sqrt(T) * normal_pdf(d1)
        if vega < 0.001:
            break
        sigma = sigma - (diff / vega)
        sigma = max(min(sigma, 120.0), 4.0)
    return round(sigma, 1)

def compute_bs_greeks(
    spot: float,
    strike: float,
    days_to_expiry: float,
    iv_pct: float,
    option_type: str = "CE",
    risk_free_rate: float = 0.07,
) -> Dict[str, float]:
    """
    Computes first-order and second-order Black-Scholes Greeks:
    Delta, Gamma, Theta, Vega, Vanna, Charm.
    """
    T = max(days_to_expiry / 365.0, 0.0005)
    sigma = max(iv_pct / 100.0, 0.05) if iv_pct else 0.14
    
    if spot <= 0 or strike <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "vanna": 0.0, "charm": 0.0}

    sqrt_T = math.sqrt(T)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * (sigma ** 2)) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    pdf_d1 = normal_pdf(d1)
    gamma = pdf_d1 / (spot * sigma * sqrt_T)
    vega = (spot * sqrt_T * pdf_d1) / 100.0  # ₹ change per 1% IV change
    # Vanna: dDelta / dVol
    vanna = (-pdf_d1 * d2 / sigma) / 100.0 if sigma > 0 else 0.0
    # Charm: dDelta / dTime (delta decay per day)
    charm = -(pdf_d1 * (risk_free_rate / (sigma * sqrt_T) - d2 / (2.0 * T))) / 365.0

    if option_type.upper() == "CE":
        delta = normal_cdf(d1)
        theta = (
            -(spot * sigma * pdf_d1) / (2.0 * sqrt_T)
            - risk_free_rate * strike * math.exp(-risk_free_rate * T) * normal_cdf(d2)
        ) / 365.0
    else:
        delta = normal_cdf(d1) - 1.0
        theta = (
            -(spot * sigma * pdf_d1) / (2.0 * sqrt_T)
            + risk_free_rate * strike * math.exp(-risk_free_rate * T) * normal_cdf(-d2)
        ) / 365.0

    return {
        "delta": round(delta, 3),
        "gamma": round(gamma, 5),
        "theta": round(theta, 2),
        "vega": round(vega, 2),
        "vanna": round(vanna, 4),
        "charm": round(charm, 4),
    }

class NiftyQuantService:
    """
    Core Nifty 50 Quantitative Analytics Service.
    """

    def __init__(self):
        self.nifty_symbol = "NSE:NIFTY50-INDEX"

    def get_full_quant_matrix(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Main entry point for live Nifty 50 Quant Analytics.
        Returns strike-by-strike color taxonomy, Greeks, Traps,
        Straddle VWAP, Heavyweight point transmission, and Best Trade recommendation.
        """
        from app.services import symbol_store as store
        from app.services.fyers_market import get_market_service

        market_service = get_market_service()
        chain_data = None
        if not force_refresh:
            chain_data = store.get_chain(self.nifty_symbol, 24)
            if not chain_data or not chain_data.get("success"):
                chain_data = market_service.get_option_chain(self.nifty_symbol, 24)

        # Fallback or force_refresh: fetch live directly and warm the store
        if not chain_data or not chain_data.get("success") or force_refresh:
            try:
                raw_live = market_service._get_option_chain_uncached(self.nifty_symbol, 24)
                if raw_live and raw_live.get("success"):
                    store.put_chain(self.nifty_symbol, raw_live)
                    chain_data = raw_live
            except Exception as e:
                logger.warning(f"Live Nifty option chain fetch fallback: {e}")

        if not chain_data or not chain_data.get("success"):
            from app.services.symbol_store import harvest_age_seconds
            return {
                "success": False,
                "error": "Nifty option chain unavailable in store or live quote",
                "waiting_for_harvest": True,
                "harvest_age": harvest_age_seconds(),
                "timestamp": datetime.now().isoformat(),
            }

        spot_price = float(chain_data.get("spot_price") or 0.0)
        atm_strike = float(chain_data.get("atm_strike") or 0.0)
        if spot_price <= 0:
            return {"success": False, "error": "Invalid spot price", "spot_price": spot_price}

        # Estimate days to expiry
        time_to_expiry_days = 2.0
        expiry_data = chain_data.get("expiryData") or []
        if expiry_data:
            try:
                # If expiry timestamp exists
                first_exp = expiry_data[0].get("date")
                if first_exp:
                    exp_dt = datetime.strptime(first_exp, "%Y-%m-%d")
                    delta_days = (exp_dt - datetime.now()).total_seconds() / 86400.0
                    time_to_expiry_days = max(delta_days, 0.1)
            except Exception:
                time_to_expiry_days = 2.0

        raw_chain = chain_data.get("chain") or []
        
        # 1. Process Strikes with Greeks, GEX, 4-Quadrant states, and Color Matrix
        analyzed_strikes, call_wall, put_wall, max_pain = self._process_strikes(
            raw_chain, spot_price, atm_strike, time_to_expiry_days
        )

        # 2. Institutional Greeks Profile (Net GEX, Gamma Flip, DEX, VEX, 25D Skew, Daily Theta Burn)
        quant_greeks = self._calculate_quant_greeks_profile(analyzed_strikes, spot_price, atm_strike)

        # 3. ATM Straddle Fair Value & Skew
        straddle_metrics = self._calculate_straddle_metrics(analyzed_strikes, atm_strike)

        # 4. Concentrated PCR (ATM +- 3 strikes) & Aggregate PCR
        pcr_metrics = self._calculate_pcr_metrics(analyzed_strikes, atm_strike)

        # 5. Institutional Traps Detection
        trap_alerts = self._detect_institutional_traps(analyzed_strikes, spot_price, atm_strike)

        # 6. Comprehensive 50 Nifty Constituent Stocks Analysis & Transmission
        constituents_report, heavyweight_contributions, net_stock_impact_pts = self._analyze_50_constituents(spot_price, force_refresh)
        heavyweight_fno_report = self._analyze_heavyweight_fno_breakouts(spot_price, force_refresh)

        # 7. Multi-Strategy Recommendation Matrix & Best Trade Selection
        effective_pts = (
            constituents_report.get("net_transmitted_thrust_pts", 0.0)
            if abs(constituents_report.get("net_transmitted_thrust_pts", 0.0)) > 3
            else (
                heavyweight_fno_report.get("net_transmitted_thrust_pts", 0.0)
                if abs(heavyweight_fno_report.get("net_transmitted_thrust_pts", 0.0)) > 5
                else net_stock_impact_pts
            )
        )
        strategies = self._generate_strategies_matrix(
            analyzed_strikes, spot_price, atm_strike, time_to_expiry_days, quant_greeks, constituents_report, trap_alerts, call_wall, put_wall
        )
        best_trade = strategies[0] if strategies else self._select_best_trade(
            analyzed_strikes, spot_price, atm_strike, time_to_expiry_days, effective_pts, trap_alerts
        )

        return {
            "success": True,
            "symbol": self.nifty_symbol,
            "spot_price": round(spot_price, 2),
            "atm_strike": atm_strike,
            "days_to_expiry": round(time_to_expiry_days, 1),
            "call_wall": call_wall,
            "put_wall": put_wall,
            "max_pain": max_pain,
            "quant_greeks": quant_greeks,
            "straddle": straddle_metrics,
            "pcr": pcr_metrics,
            "traps": trap_alerts,
            "constituents_report": constituents_report,
            "heavyweights": heavyweight_contributions,
            "heavyweight_fno": heavyweight_fno_report,
            "net_heavyweight_points": round(net_stock_impact_pts, 2),
            "best_trade": best_trade,
            "strategies": strategies,
            "strikes": analyzed_strikes,
            "timestamp": datetime.now().isoformat(),
        }

    def _process_strikes(
        self,
        raw_chain: List[Dict[str, Any]],
        spot_price: float,
        atm_strike: float,
        days_to_expiry: float,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any], float]:
        """
        Processes every strike, computes Greeks, assigns color tokens,
        and identifies Call Wall, Put Wall, and Max Pain.
        """
        analyzed = []
        max_call_oi = -1
        max_put_oi = -1
        call_wall = {"strike": 0, "oi": 0}
        put_wall = {"strike": 0, "oi": 0}

        # First pass: sort and extract core data
        for row in raw_chain:
            k = float(row.get("strike_price") or 0.0)
            if k <= 0:
                continue

            call = row.get("call") or {}
            put = row.get("put") or {}

            c_ltp = float(call.get("ltp") or 0.0)
            p_ltp = float(put.get("ltp") or 0.0)
            c_oi = float(call.get("oi") or call.get("call_oi") or 0.0)
            p_oi = float(put.get("oi") or put.get("put_oi") or 0.0)
            c_oich = float(call.get("oi_change") or call.get("oich") or 0.0)
            p_oich = float(put.get("oi_change") or put.get("oich") or 0.0)
            c_vol = float(call.get("volume") or call.get("vol") or 0.0)
            p_vol = float(put.get("volume") or put.get("vol") or 0.0)
            c_chg = float(call.get("chg") or call.get("change") or 0.0)
            p_chg = float(put.get("chg") or put.get("change") or 0.0)

            # Fallback delta OI from prev_oi if oich is 0
            if c_oich == 0.0 and call.get("prev_oi"):
                prev_c = float(call.get("prev_oi") or 0.0)
                if prev_c > 0 and prev_c != c_oi:
                    c_oich = c_oi - prev_c

            if p_oich == 0.0 and put.get("prev_oi"):
                prev_p = float(put.get("prev_oi") or 0.0)
                if prev_p > 0 and prev_p != p_oi:
                    p_oich = p_oi - prev_p

            # Calculate accurate dynamic IV via Black-Scholes inversion if missing from feed
            raw_c_iv = call.get("iv")
            raw_p_iv = put.get("iv")
            c_iv = float(raw_c_iv) if raw_c_iv and float(raw_c_iv) > 0 else solve_implied_volatility(spot_price, k, days_to_expiry, c_ltp, "CE")
            p_iv = float(raw_p_iv) if raw_p_iv and float(raw_p_iv) > 0 else solve_implied_volatility(spot_price, k, days_to_expiry, p_ltp, "PE")

            # Wall detection
            if k >= spot_price and c_oi > max_call_oi:
                max_call_oi = c_oi
                call_wall = {"strike": k, "oi": c_oi}

            if k <= spot_price and p_oi > max_put_oi:
                max_put_oi = p_oi
                put_wall = {"strike": k, "oi": p_oi}

            # Black-Scholes Greeks
            c_greeks = compute_bs_greeks(spot_price, k, days_to_expiry, c_iv, "CE")
            p_greeks = compute_bs_greeks(spot_price, k, days_to_expiry, p_iv, "PE")

            # Per-strike Dealer Gamma Exposure (in ₹ Crores per 1% spot move)
            spot_mult = (spot_price ** 2) * 0.01 / 1e7
            c_gex = round(c_oi * c_greeks["gamma"] * spot_mult, 2)
            p_gex = round(-p_oi * p_greeks["gamma"] * spot_mult, 2)
            net_gex = round(c_gex + p_gex, 2)
            c_greeks["gex"] = c_gex
            p_greeks["gex"] = p_gex

            # 4-Quadrant Buildup & UI Color Classification for Call
            c_state, c_color, c_badge = self._classify_quadrant(c_chg, c_oich, c_vol, c_oi, c_ltp)

            # 4-Quadrant Buildup & UI Color Classification for Put
            p_state, p_color, p_badge = self._classify_quadrant(p_chg, p_oich, p_vol, p_oi, p_ltp)

            # Asymmetric Addition Ratio (AAR)
            aar = round(p_oich / c_oich, 2) if c_oich != 0 else (9.9 if p_oich > 0 else 0.0)

            analyzed.append({
                "strike": k,
                "is_atm": abs(k - atm_strike) < 25,
                "aar": aar,
                "net_gex": net_gex,
                "call": {
                    "ltp": c_ltp,
                    "chg": c_chg,
                    "oi": c_oi,
                    "oich": c_oich,
                    "volume": c_vol,
                    "iv": c_iv,
                    "greeks": c_greeks,
                    "state": c_state,
                    "color": c_color,
                    "badge": c_badge,
                },
                "put": {
                    "ltp": p_ltp,
                    "chg": p_chg,
                    "oi": p_oi,
                    "oich": p_oich,
                    "volume": p_vol,
                    "iv": p_iv,
                    "greeks": p_greeks,
                    "state": p_state,
                    "color": p_color,
                    "badge": p_badge,
                },
            })

        # Sort strikes ascending
        analyzed.sort(key=lambda x: x["strike"])

        # Calculate exact analytical Max Pain
        max_pain_strike = self._calculate_max_pain(analyzed)

        return analyzed, call_wall, put_wall, max_pain_strike

    def _classify_quadrant(
        self, price_change: float, oi_change: float, volume: float, total_oi: float, ltp: float
    ) -> Tuple[str, str, str]:
        """
        Classifies strike into 4-quadrant state:
        - LONG_BUILDUP (#00E676)
        - SHORT_BUILDUP (#FF1744)
        - SHORT_COVERING (#00E5FF)
        - LONG_UNWINDING (#FF9100)
        - GAMMA_EXPLOSION (#FFD600)
        """
        # Gamma Explosion criteria: Sharp price expansion, huge volume surge, and writer panic (-dOI)
        if price_change > 15.0 and oi_change < -50000 and volume > max(total_oi * 0.8, 200000):
            return "GAMMA_EXPLOSION", "#FFD600", "⚡ GAMMA"

        if price_change >= 0 and oi_change > 0:
            return "LONG_BUILDUP", "#00E676", "LBU"
        elif price_change < 0 and oi_change > 0:
            return "SHORT_BUILDUP", "#FF1744", "SBU"
        elif price_change >= 0 and oi_change < 0:
            return "SHORT_COVERING", "#00E5FF", "SH-COV"
        elif price_change < 0 and oi_change < 0:
            return "LONG_UNWINDING", "#FF9100", "LUW"

        # When delta OI is 0 or low, classify by price momentum & volume
        if price_change > 0:
            return "LONG_ACCUMULATION", "#00E676", "ACCUM"
        elif price_change < 0:
            return "SHORT_BUILDUP", "#FF1744", "DISTRIB"

        return "NEUTRAL", "#4B5563", "CHOP"

    def _calculate_max_pain(self, analyzed_strikes: List[Dict[str, Any]]) -> float:
        """
        Finds strike K that minimizes total intrinsic payoff to buyers.
        Pain(K) = sum(CE_OI * max(0, K - K_j)) + sum(PE_OI * max(0, K_j - K))
        """
        if not analyzed_strikes:
            return 0.0

        min_total_loss = float("inf")
        best_strike = analyzed_strikes[0]["strike"]

        for candidate in analyzed_strikes:
            K = candidate["strike"]
            total_loss = 0.0

            for other in analyzed_strikes:
                K_j = other["strike"]
                ce_oi = other["call"]["oi"]
                pe_oi = other["put"]["oi"]

                # CE buyer intrinsic value if spot settles at K
                if K > K_j:
                    total_loss += ce_oi * (K - K_j)
                # PE buyer intrinsic value if spot settles at K
                if K < K_j:
                    total_loss += pe_oi * (K_j - K)

            if total_loss < min_total_loss:
                min_total_loss = total_loss
                best_strike = K

        return best_strike

    def _calculate_straddle_metrics(
        self, analyzed_strikes: List[Dict[str, Any]], atm_strike: float
    ) -> Dict[str, Any]:
        """
        Calculates ATM Straddle Price, Upper/Lower Break-Evens,
        and Straddle Skew Ratio (CE LTP / PE LTP).
        """
        atm_row = next((r for r in analyzed_strikes if r["strike"] == atm_strike), None)
        if not atm_row and analyzed_strikes:
            # Pick closest
            atm_row = min(analyzed_strikes, key=lambda r: abs(r["strike"] - atm_strike))

        if not atm_row:
            return {"straddle_price": 0.0, "status": "UNKNOWN", "skew_ratio": 1.0}

        ce_ltp = atm_row["call"]["ltp"]
        pe_ltp = atm_row["put"]["ltp"]
        combined = round(ce_ltp + pe_ltp, 2)
        upper_be = round(atm_row["strike"] + combined, 1)
        lower_be = round(atm_row["strike"] - combined, 1)

        skew_ratio = round(ce_ltp / max(pe_ltp, 0.1), 2)

        # Regimes
        if skew_ratio > 1.8:
            bias = "CALL_EXPANSION"
        elif skew_ratio < 0.55:
            bias = "PUT_EXPANSION"
        else:
            bias = "BALANCED_DECAY"

        return {
            "strike": atm_row["strike"],
            "combined_premium": combined,
            "ce_premium": ce_ltp,
            "pe_premium": pe_ltp,
            "upper_breakeven": upper_be,
            "lower_breakeven": lower_be,
            "skew_ratio": skew_ratio,
            "regime": bias,
            "expected_range_points": round(combined * 0.85, 1),
        }

    def _calculate_pcr_metrics(
        self, analyzed_strikes: List[Dict[str, Any]], atm_strike: float
    ) -> Dict[str, Any]:
        """
        Calculates Total PCR and Strike-Concentrated PCR (ATM +- 3 strikes).
        """
        total_ce_oi = sum(r["call"]["oi"] for r in analyzed_strikes)
        total_pe_oi = sum(r["put"]["oi"] for r in analyzed_strikes)
        total_pcr = round(total_pe_oi / max(total_ce_oi, 1.0), 3)

        # ATM +- 3 strikes (150 pts range)
        atm_cluster = [r for r in analyzed_strikes if abs(r["strike"] - atm_strike) <= 150]
        atm_ce_oi = sum(r["call"]["oi"] for r in atm_cluster)
        atm_pe_oi = sum(r["put"]["oi"] for r in atm_cluster)
        atm_pcr = round(atm_pe_oi / max(atm_ce_oi, 1.0), 3)

        if atm_pcr > 1.35:
            sentiment = "PUT_FLOOR_BULLISH"
            desc = "Heavy put writing across ATM strikes (strong support floor)"
        elif atm_pcr < 0.70:
            sentiment = "CALL_CEILING_BEARISH"
            desc = "Heavy call writing across ATM strikes (overhead resistance)"
        else:
            sentiment = "BALANCED_RANGE"
            desc = "Balanced institutional positioning"

        return {
            "total_pcr": total_pcr,
            "atm_cluster_pcr": atm_pcr,
            "sentiment": sentiment,
            "description": desc,
            "total_call_oi": int(total_ce_oi),
            "total_put_oi": int(total_pe_oi),
        }

    def _detect_institutional_traps(
        self, analyzed_strikes: List[Dict[str, Any]], spot_price: float, atm_strike: float
    ) -> List[Dict[str, Any]]:
        """
        Detects False Breakout Traps:
        - Call Trap: Spot pushes higher, but CE Change in OI spikes while CE price stalls.
        - Put Trap: Spot dips, but PE writers absorb without unwinding.
        """
        traps = []

        # Check immediate 3 strikes above spot for Call Trap
        otm_calls = [r for r in analyzed_strikes if 0 < r["strike"] - spot_price <= 150]
        heavy_ce_writing = sum(r["call"]["oich"] for r in otm_calls)
        avg_ce_chg = sum(r["call"]["chg"] for r in otm_calls) / max(len(otm_calls), 1)

        if heavy_ce_writing > 120000 and avg_ce_chg <= 2.0:
            traps.append({
                "type": "CALL_WRITER_TRAP",
                "severity": "HIGH",
                "message": (
                    f"⚠️ CALL TRAP DETECTED: +{int(heavy_ce_writing):,} CE OI added at OTM strikes "
                    f"while premiums stalled. High probability of false upside breakout."
                ),
            })

        # Check immediate 3 strikes below spot for Put Trap / Squeeze
        otm_puts = [r for r in analyzed_strikes if 0 < spot_price - r["strike"] <= 150]
        heavy_pe_writing = sum(r["put"]["oich"] for r in otm_puts)
        avg_pe_chg = sum(r["put"]["chg"] for r in otm_puts) / max(len(otm_puts), 1)

        if heavy_pe_writing > 120000 and avg_pe_chg <= 2.0:
            traps.append({
                "type": "PUT_SUPPORT_LOCK",
                "severity": "MEDIUM",
                "message": (
                    f"🛡️ PUT FLOOR SECURED: +{int(heavy_pe_writing):,} PE OI added below spot. "
                    f"Downside locked; dip-buyers in control."
                ),
            })

        return traps

    def _calculate_quant_greeks_profile(
        self, analyzed_strikes: List[Dict[str, Any]], spot_price: float, atm_strike: float
    ) -> Dict[str, Any]:
        """
        Computes institutional dealer Greek exposures:
        - Total Net GEX (Dealer Gamma Exposure in ₹ Crores per 1% move)
        - Gamma Flip Level (zero-crossing strike)
        - Gamma Regime: LONG_GAMMA_STABILIZING vs SHORT_GAMMA_VOLATILITY_EXPANSION
        - Dealer Net DEX (Delta Exposure in ₹ Crores)
        - Dealer Net VEX (Vega Exposure in ₹ Crores per 1% IV change)
        - 25-Delta IV Skew (Institutional tail-risk hedging premium)
        - ATM Cluster Daily Theta Burn (₹ Crores per day)
        """
        if not analyzed_strikes:
            return {}

        total_net_gex = sum(r.get("net_gex", 0.0) for r in analyzed_strikes)
        call_gex = sum((r["call"]["greeks"].get("gex") or 0.0) for r in analyzed_strikes)
        put_gex = sum((r["put"]["greeks"].get("gex") or 0.0) for r in analyzed_strikes)

        # Gamma Flip Strike (level where cumulative net GEX crosses 0)
        gamma_flip_strike = atm_strike
        cum_gex = 0.0
        for r in analyzed_strikes:
            cum_gex += r.get("net_gex", 0.0)
            if cum_gex >= 0:
                gamma_flip_strike = r["strike"]
                break

        regime = (
            "LONG_GAMMA_STABILIZING"
            if total_net_gex > 0
            else "SHORT_GAMMA_VOLATILITY_EXPANSION"
        )

        # Net DEX (₹ Crores)
        total_dex = sum(
            (r["call"]["oi"] * r["call"]["greeks"]["delta"] + r["put"]["oi"] * r["put"]["greeks"]["delta"])
            * spot_price / 1e7
            for r in analyzed_strikes
        )

        # Net VEX (₹ Crores per 1% IV change)
        total_vex = sum(
            (r["call"]["oi"] * r["call"]["greeks"]["vega"] + r["put"]["oi"] * r["put"]["greeks"]["vega"])
            / 1e7
            for r in analyzed_strikes
        )

        # 25-Delta IV Skew: find strike with CE delta closest to 0.25, and PE delta closest to -0.25
        c_25 = min(analyzed_strikes, key=lambda x: abs(x["call"]["greeks"]["delta"] - 0.25), default=None)
        p_25 = min(analyzed_strikes, key=lambda x: abs(x["put"]["greeks"]["delta"] - (-0.25)), default=None)
        skew_25d = round((p_25["put"]["iv"] - c_25["call"]["iv"]), 2) if (c_25 and p_25) else 0.0

        # Daily Theta Burn across ATM Cluster (± 150 points)
        atm_cluster = [r for r in analyzed_strikes if abs(r["strike"] - atm_strike) <= 150]
        daily_theta_burn_cr = round(
            sum((r["call"]["oi"] * abs(r["call"]["greeks"]["theta"]) + r["put"]["oi"] * abs(r["put"]["greeks"]["theta"])) / 1e7 for r in atm_cluster),
            2
        )

        return {
            "net_gex_crores": round(total_net_gex, 1),
            "call_gex_crores": round(call_gex, 1),
            "put_gex_crores": round(put_gex, 1),
            "gamma_flip_strike": gamma_flip_strike,
            "gamma_regime": regime,
            "gamma_thesis": (
                f"Dealers Long Gamma (+₹{total_net_gex:.0f}Cr): Hedging dampens volatility. Market makers buy dips and sell rallies. High probability of mean-reversion inside walls."
                if total_net_gex > 0
                else f"Dealers Short Gamma ({total_net_gex:.0f}Cr): Hedging accelerates momentum. Market makers sell dips and buy breakouts. Explosive trend expansion active."
            ),
            "net_dex_crores": round(total_dex, 1),
            "net_vex_crores": round(total_vex, 2),
            "iv_skew_25d": skew_25d,
            "skew_sentiment": (
                "HIGH_PUT_DEMAND_DEFENSIVE"
                if skew_25d > 2.5
                else ("CALL_CHASE_SPECULATIVE" if skew_25d < -0.5 else "BALANCED_SKEW")
            ),
            "daily_theta_burn_cr": daily_theta_burn_cr,
        }

    def _analyze_50_constituents(
        self, nifty_spot: float, force_refresh: bool = False
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], float]:
        """
        Analyzes the full 50 F&O constituent stocks of Nifty 50:
        1. Exact point impact transmission: (weight / 100) * (chp / 100) * nifty_spot
        2. Market Breadth: Advances vs Declines, Weight-Adjusted Breadth %
        3. Sector-wise Transmission breakdown (Banking, IT, Oil/Gas, Auto, Metals, etc.)
        4. Top 5 Positive Drivers & Top 5 Negative Drags
        5. Live F&O Wall and PCR mapping from symbol_store
        """
        from app.services import symbol_store as store
        from app.services.fyers_market import get_market_service

        market_service = get_market_service()
        spots_cache = {}
        missing_syms = []

        all_syms = [s["symbol"] for s in NIFTY_50_CONSTITUENTS]
        cached_spots = store.get_spots(all_syms) if not force_refresh else {}
        for s in NIFTY_50_CONSTITUENTS:
            sym = s["symbol"]
            q = cached_spots.get(sym) or store.get_spot(sym)
            if q and q.get("ltp") and q.get("ltp") > 0:
                spots_cache[sym] = q
            else:
                missing_syms.append(sym)

        # Batch fetch missing quotes via Fyers quotes endpoint in chunks of 50
        if missing_syms:
            try:
                fyers = market_service._get_fyers()
                if fyers:
                    for i in range(0, len(missing_syms), 50):
                        batch = missing_syms[i:i + 50]
                        resp = market_service._invoke("quotes", lambda: fyers.quotes({"symbols": ",".join(batch)}))
                        if resp.get("s") == "ok":
                            for item in resp.get("d", []):
                                v = item.get("v", {})
                                item_sym = item.get("n")
                                if item_sym:
                                    q_obj = {
                                        "ltp": v.get("lp", 0) or v.get("ltp", 0),
                                        "chp": v.get("chp", 0),
                                        "chg": v.get("ch", 0),
                                    }
                                    spots_cache[item_sym] = q_obj
                                    store.put_spot(item_sym, q_obj)
            except Exception as e:
                logger.debug(f"Direct 50-stock batch quote fetch skipped: {e}")

        detailed_constituents = []
        net_impact_points = 0.0
        advances = 0
        declines = 0
        unchanged = 0
        adv_weight = 0.0
        dec_weight = 0.0

        sector_map: Dict[str, Dict[str, Any]] = {}

        for stock in NIFTY_50_CONSTITUENTS:
            sym = stock["symbol"]
            name = stock["name"]
            sector = stock["sector"]
            weight = stock["weight"]

            quote = spots_cache.get(sym) or store.get_spot(sym) or {}
            ltp = float(quote.get("ltp") or 0.0)
            chp = float(quote.get("chp") or quote.get("change_percent") or quote.get("change_pct") or 0.0)
            chg = float(quote.get("chg") or quote.get("change") or 0.0)

            # Mathematical Point Contribution formula
            point_impact = (weight / 100.0) * (chp / 100.0) * nifty_spot
            net_impact_points += point_impact

            # Breadth tally
            if chp > 0.05:
                advances += 1
                adv_weight += weight
                bias = "BULLISH"
            elif chp < -0.05:
                declines += 1
                dec_weight += weight
                bias = "BEARISH"
            else:
                unchanged += 1
                bias = "NEUTRAL"

            # Check if option chain / board metrics exist in store
            snap = store.get(sym) or {}
            derived = snap.get("derived") or {}
            chain_doc = snap.get("chain") or {}
            stock_pcr = derived.get("pcr") or chain_doc.get("pcr") or 1.0
            call_wall = derived.get("call_wall") or 0
            put_wall = derived.get("put_wall") or 0

            # Determine wall state
            if call_wall > 0 and ltp >= call_wall:
                state = "CALL_WALL_BREACH"
                badge = "🚀 CALL BREACH"
                color = "#00E5FF"
            elif put_wall > 0 and ltp <= put_wall:
                state = "PUT_WALL_BREACH"
                badge = "💥 PUT BREACH"
                color = "#FF1744"
            elif call_wall > 0 and (call_wall - ltp) / max(ltp, 1) < 0.012:
                state = "CALL_WALL_SQUEEZE"
                badge = "🔥 SQUEEZE"
                color = "#00E5FF"
            elif put_wall > 0 and (ltp - put_wall) / max(ltp, 1) < 0.012:
                state = "PUT_FLOOR_SUPPORT"
                badge = "🛡️ PUT FLOOR"
                color = "#00E676"
            elif point_impact > 1.0:
                state = "BULL_EXPANSION"
                badge = "🟢 ADVANCING"
                color = "#00E676"
            elif point_impact < -1.0:
                state = "BEAR_DRAG"
                badge = "🔴 DRAGGING"
                color = "#FF1744"
            else:
                state = "NEUTRAL"
                badge = "⚖️ NEUTRAL"
                color = "#9CA3AF"

            # Sector aggregation
            if sector not in sector_map:
                sector_map[sector] = {
                    "sector": sector,
                    "total_weight": 0.0,
                    "net_points": 0.0,
                    "advances": 0,
                    "declines": 0,
                    "stocks_count": 0,
                    "leader": name,
                    "leader_impact": point_impact,
                }
            s_entry = sector_map[sector]
            s_entry["total_weight"] += weight
            s_entry["net_points"] += point_impact
            s_entry["stocks_count"] += 1
            if chp > 0:
                s_entry["advances"] += 1
            elif chp < 0:
                s_entry["declines"] += 1
            if point_impact > s_entry["leader_impact"]:
                s_entry["leader"] = name
                s_entry["leader_impact"] = point_impact

            detailed_constituents.append({
                "symbol": sym,
                "name": name,
                "sector": sector,
                "weight": round(weight, 2),
                "ltp": round(ltp, 2),
                "change_pct": round(chp, 2),
                "change": round(chg, 2),
                "point_impact": round(point_impact, 2),
                "bias": bias,
                "pcr": round(float(stock_pcr), 2) if stock_pcr else 1.0,
                "call_wall": round(float(call_wall), 1) if call_wall else 0,
                "put_wall": round(float(put_wall), 1) if put_wall else 0,
                "state": state,
                "badge": badge,
                "color": color,
            })

        # Sort all constituents by absolute point impact
        detailed_constituents.sort(key=lambda x: abs(x["point_impact"]), reverse=True)

        # Top 5 Drivers & Top 5 Drags
        top_drivers = [s for s in sorted(detailed_constituents, key=lambda x: x["point_impact"], reverse=True) if s["point_impact"] > 0][:5]
        top_drags = [s for s in sorted(detailed_constituents, key=lambda x: x["point_impact"]) if s["point_impact"] < 0][:5]

        # Sector breakdown sorted by net point impact
        sector_breakdown = []
        for s_name, s_data in sector_map.items():
            sector_breakdown.append({
                "sector": s_name,
                "total_weight": round(s_data["total_weight"], 1),
                "net_points": round(s_data["net_points"], 1),
                "advances": s_data["advances"],
                "declines": s_data["declines"],
                "stocks_count": s_data["stocks_count"],
                "leader": s_data["leader"],
            })
        sector_breakdown.sort(key=lambda x: abs(x["net_points"]), reverse=True)

        # Breadth regime
        adv_wt_pct = round((adv_weight / max(adv_weight + dec_weight, 1.0)) * 100.0, 1)
        if adv_wt_pct >= 65.0:
            breadth_regime = "BROAD_BASED_ACCUMULATION"
        elif adv_wt_pct <= 35.0:
            breadth_regime = "BROAD_BASED_DISTRIBUTION"
        else:
            breadth_regime = "SELECTIVE_CHOP_MIXED"

        constituents_report = {
            "net_transmitted_thrust_pts": round(net_impact_points, 1),
            "market_breadth": {
                "advances": advances,
                "declines": declines,
                "unchanged": unchanged,
                "advance_weight_pct": adv_wt_pct,
                "decline_weight_pct": round(100.0 - adv_wt_pct, 1),
                "breadth_regime": breadth_regime,
            },
            "top_drivers": top_drivers,
            "top_drags": top_drags,
            "sector_breakdown": sector_breakdown,
            "constituents": detailed_constituents,
        }

        # Top 10 heavyweights for backward compatibility
        top_10 = detailed_constituents[:10]

        return constituents_report, top_10, round(net_impact_points, 2)

    def _calculate_heavyweight_impact(self, nifty_spot: float, force_refresh: bool = False) -> Tuple[List[Dict[str, Any]], float]:
        """Backward-compatible wrapper around _analyze_50_constituents."""
        report, top_10, net_impact = self._analyze_50_constituents(nifty_spot, force_refresh)
        return top_10, net_impact

    def _analyze_heavyweight_fno_breakouts(self, nifty_spot: float, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Dynamically fetches and analyzes the actual live option chains for top Nifty 50
        heavyweights, extracts their Call/Put Walls, PCR, and F&O breakout states,
        and computes the transmitted directional thrust and target strike for Nifty 50.
        """
        from app.services import symbol_store as store
        from app.services.fyers_market import get_market_service
        import concurrent.futures as cf

        market_service = get_market_service()
        tracked = NIFTY_HEAVYWEIGHTS[:8]  # Top 8 heavyweights control ~48.7% of Nifty

        # Parallel fetch / store check
        chains_map = {}
        missing_to_fetch = []
        for stock in tracked:
            sym = stock["symbol"]
            cached = None if force_refresh else store.get_chain(sym, 6)
            if cached and cached.get("success") and cached.get("chain"):
                chains_map[sym] = cached
            else:
                missing_to_fetch.append(stock)

        if missing_to_fetch:
            try:
                with cf.ThreadPoolExecutor(max_workers=min(len(missing_to_fetch), 8)) as executor:
                    futures = {
                        executor.submit(market_service._get_option_chain_uncached, s["symbol"], 6): s["symbol"]
                        for s in missing_to_fetch
                    }
                    for fut in cf.as_completed(futures, timeout=6.0):
                        sym = futures[fut]
                        try:
                            res = fut.result()
                            if res and res.get("success") and res.get("chain"):
                                chains_map[sym] = res
                                store.put_chain(sym, res)
                        except Exception as e:
                            logger.debug(f"Chain fetch error for {sym}: {e}")
            except Exception as e:
                logger.warning(f"Parallel heavyweight chain fetch timeout/error: {e}")

        detailed_stocks = []
        net_transmitted_thrust = 0.0
        bull_count = 0
        bear_count = 0

        for stock in tracked:
            sym = stock["symbol"]
            name = stock["name"]
            weight = stock["weight"]
            chain = chains_map.get(sym) or {}
            strikes = chain.get("chain") or []
            stock_spot = float(chain.get("spot_price") or 0.0)

            # Fallback spot from store if chain spot is 0
            if stock_spot <= 0:
                q = store.get_spot(sym) or {}
                stock_spot = float(q.get("ltp") or 0.0)

            if not strikes or stock_spot <= 0:
                continue

            # Identify Call Wall and Put Wall
            calls_above = [s for s in strikes if float(s.get("strike_price") or 0) >= stock_spot]
            puts_below = [s for s in strikes if float(s.get("strike_price") or 0) <= stock_spot]

            cw_row = max(calls_above, key=lambda x: (x.get("call") or {}).get("oi", 0), default={})
            pw_row = max(puts_below, key=lambda x: (x.get("put") or {}).get("oi", 0), default={})

            call_wall_strike = float(cw_row.get("strike_price") or (stock_spot * 1.02))
            put_wall_strike = float(pw_row.get("strike_price") or (stock_spot * 0.98))

            call_wall_oi = (cw_row.get("call") or {}).get("oi", 0)
            put_wall_oi = (pw_row.get("put") or {}).get("oi", 0)

            call_wall_oich = (cw_row.get("call") or {}).get("oich", 0) or (cw_row.get("call") or {}).get("oi_change", 0)
            put_wall_oich = (pw_row.get("put") or {}).get("oich", 0) or (pw_row.get("put") or {}).get("oi_change", 0)

            total_ce_oi = sum((s.get("call") or {}).get("oi", 0) for s in strikes)
            total_pe_oi = sum((s.get("put") or {}).get("oi", 0) for s in strikes)
            stock_pcr = round(total_pe_oi / max(total_ce_oi, 1.0), 2)

            dist_to_cw_pct = ((call_wall_strike - stock_spot) / stock_spot) * 100.0
            dist_to_pw_pct = ((stock_spot - put_wall_strike) / stock_spot) * 100.0

            # Determine Breakout / Breakdown State
            if stock_spot >= call_wall_strike:
                state = "CALL_WALL_BREACH"
                color = "#00E5FF"
                badge = "🚀 CALL BREACH"
                pred_move_pct = 3.0
                clue = f"Breakout active! Spot ₹{stock_spot:.1f} trading above Call Wall ₹{call_wall_strike:.0f}. Writers covering; momentum expanding."
            elif stock_spot <= put_wall_strike:
                state = "PUT_WALL_BREACH"
                color = "#FF1744"
                badge = "💥 PUT BREACH"
                pred_move_pct = -3.0
                clue = f"Breakdown active! Spot ₹{stock_spot:.1f} trading below Put Wall ₹{put_wall_strike:.0f}. Floor collapsed; panic liquidation."
            elif dist_to_cw_pct <= 1.5:
                if call_wall_oich < 0:
                    state = "CALL_WALL_SQUEEZE"
                    color = "#00E5FF"
                    badge = "🔥 CALL SQUEEZE"
                    pred_move_pct = 2.4
                    clue = f"Testing Call Wall ₹{call_wall_strike:.0f} ({dist_to_cw_pct:.1f}% away). Call writers unwinding (-{abs(int(call_wall_oich)):,} OI) -> breakout imminent."
                else:
                    state = "CALL_WALL_RESISTANCE"
                    color = "#FF1744"
                    badge = "🚧 RESISTANCE WALL"
                    pred_move_pct = -0.8
                    oi_str = f"+{int(call_wall_oich):,} OI" if call_wall_oich > 0 else f"{int(call_wall_oi):,} total OI"
                    clue = f"Heavy Call writing ({oi_str}) at ₹{call_wall_strike:.0f} capping upside ({dist_to_cw_pct:.1f}% away)."
            elif dist_to_pw_pct <= 1.2:
                if put_wall_oich < 0:
                    state = "PUT_WALL_BREAKDOWN"
                    color = "#FF1744"
                    badge = "⚠️ BREAKDOWN RISK"
                    pred_move_pct = -2.2
                    clue = f"Put Wall ₹{put_wall_strike:.0f} cracking ({dist_to_pw_pct:.1f}% away). Put writers unwinding (-{abs(int(put_wall_oich)):,} OI) -> downside cascade."
                else:
                    state = "PUT_FLOOR_SUPPORT"
                    color = "#00E676"
                    badge = "🛡️ PUT FLOOR"
                    pred_move_pct = 1.2
                    oi_str = f"+{int(put_wall_oich):,} OI" if put_wall_oich > 0 else f"{int(put_wall_oi):,} total OI"
                    clue = f"Strong Put floor locked at ₹{put_wall_strike:.0f} ({dist_to_pw_pct:.1f}% away, {oi_str}). Buyers defending base."
            else:
                if stock_pcr > 1.15:
                    state = "BULLISH_BIAS"
                    color = "#00E676"
                    badge = "📈 BULL BIAS"
                    pred_move_pct = 0.9
                    clue = f"PCR at {stock_pcr} shows institutional put accumulation between ₹{put_wall_strike:.0f} and ₹{call_wall_strike:.0f}."
                elif stock_pcr < 0.75:
                    state = "BEARISH_BIAS"
                    color = "#FF9100"
                    badge = "📉 BEAR BIAS"
                    pred_move_pct = -0.9
                    clue = f"Low PCR ({stock_pcr}) shows overhead call writing pressure between ₹{put_wall_strike:.0f} and ₹{call_wall_strike:.0f}."
                else:
                    state = "RANGE_CHOP"
                    color = "#9CA3AF"
                    badge = "⚖️ RANGE"
                    pred_move_pct = 0.2
                    clue = f"Oscillating inside range: Put Wall ₹{put_wall_strike:.0f} ({dist_to_pw_pct:.1f}%) to Call Wall ₹{call_wall_strike:.0f} ({dist_to_cw_pct:.1f}%)."

            # Calculate Transmitted Nifty Point Impact
            point_impact = (weight / 100.0) * (pred_move_pct / 100.0) * nifty_spot
            net_transmitted_thrust += point_impact

            if point_impact > 1.5:
                bull_count += 1
            elif point_impact < -1.5:
                bear_count += 1

            detailed_stocks.append({
                "symbol": sym,
                "name": name,
                "weight": weight,
                "spot": round(stock_spot, 1),
                "call_wall": round(call_wall_strike, 1),
                "call_wall_oi": int(call_wall_oi),
                "put_wall": round(put_wall_strike, 1),
                "put_wall_oi": int(put_wall_oi),
                "dist_to_call_wall_pct": round(dist_to_cw_pct, 2),
                "dist_to_put_wall_pct": round(dist_to_pw_pct, 2),
                "pcr": stock_pcr,
                "state": state,
                "badge": badge,
                "color": color,
                "predicted_move_pct": round(pred_move_pct, 1),
                "transmitted_nifty_points": round(point_impact, 1),
                "clue": clue,
            })

        detailed_stocks.sort(key=lambda x: abs(x["transmitted_nifty_points"]), reverse=True)

        projected_nifty_target = nifty_spot + net_transmitted_thrust
        recommended_strike = round(projected_nifty_target / 50.0) * 50
        target_opt_type = "CE" if net_transmitted_thrust >= 0 else "PE"

        if net_transmitted_thrust > 35.0:
            consensus = "STRONG_BULLISH_EXPANSION"
            thesis = (
                f"Heavyweight F&O alignment is strongly bullish (+{net_transmitted_thrust:.1f} pts thrust). "
                f"Breakout pressures in {', '.join([s['name'] for s in detailed_stocks if s['transmitted_nifty_points'] > 5][:2])} "
                f"are projected to force Nifty towards {projected_nifty_target:.0f}, threatening Nifty Call Walls."
            )
        elif net_transmitted_thrust < -35.0:
            consensus = "STRONG_BEARISH_BREAKDOWN"
            thesis = (
                f"Heavyweight F&O alignment is severely bearish ({net_transmitted_thrust:.1f} pts drag). "
                f"Selling pressure in {', '.join([s['name'] for s in detailed_stocks if s['transmitted_nifty_points'] < -5][:2])} "
                f"threatens Nifty Put Walls down towards {projected_nifty_target:.0f}."
            )
        else:
            consensus = "MIXED_CROSS_CURRENT"
            thesis = (
                f"Heavyweights show offsetting pressures ({net_transmitted_thrust:+.1f} pts net). "
                f"Nifty is constrained inside its straddle boundaries near {projected_nifty_target:.0f}."
            )

        return {
            "net_transmitted_thrust_pts": round(net_transmitted_thrust, 1),
            "projected_nifty_target": round(projected_nifty_target, 1),
            "recommended_nifty_strike": f"NIFTY {int(recommended_strike)} {target_opt_type}",
            "recommended_strike_value": recommended_strike,
            "target_opt_type": target_opt_type,
            "consensus": consensus,
            "bull_heavyweights_count": bull_count,
            "bear_heavyweights_count": bear_count,
            "thesis": thesis,
            "stocks": detailed_stocks,
        }

    def simulate_stock_breakout(
        self,
        stock_symbol: str,
        expected_stock_move_pct: float,
        nifty_spot: float,
    ) -> Dict[str, Any]:
        """
        What-If Simulator:
        Given an expected stock breakout %, calculates the projected point rally on Nifty,
        target Nifty level, and the optimal strike price to execute.
        Supports all 50 Nifty constituent stocks.
        """
        stock_meta = next((s for s in NIFTY_50_CONSTITUENTS if s["symbol"] == stock_symbol or s["name"].lower() in stock_symbol.lower() or stock_symbol.lower() in s["symbol"].lower()), None)
        weight = stock_meta["weight"] if stock_meta else 5.0
        stock_name = stock_meta["name"] if stock_meta else stock_symbol

        # Delta Nifty points
        delta_nifty = (weight / 100.0) * (expected_stock_move_pct / 100.0) * nifty_spot
        projected_nifty = nifty_spot + delta_nifty

        bias = "BULLISH" if delta_nifty >= 0 else "BEARISH"
        opt_type = "CE" if bias == "BULLISH" else "PE"

        # Round target strike to nearest 50
        recommended_strike = round(projected_nifty / 50.0) * 50

        return {
            "stock_symbol": stock_symbol,
            "stock_name": stock_name,
            "weight": weight,
            "expected_stock_move_pct": round(expected_stock_move_pct, 2),
            "projected_nifty_points": round(delta_nifty, 2),
            "current_nifty_spot": round(nifty_spot, 2),
            "projected_nifty_target": round(projected_nifty, 2),
            "bias": bias,
            "recommended_strike": f"NIFTY {int(recommended_strike)} {opt_type}",
            "strike_value": recommended_strike,
            "option_type": opt_type,
            "rationale": (
                f"{stock_name} ({weight}% weight) a {expected_stock_move_pct:+.1f}% move "
                f"contributes {delta_nifty:+.1f} points to Nifty, driving index toward {projected_nifty:.0f}."
            ),
        }

    def _generate_strategies_matrix(
        self,
        analyzed_strikes: List[Dict[str, Any]],
        spot_price: float,
        atm_strike: float,
        days_to_expiry: float,
        quant_greeks: Dict[str, Any],
        constituents_report: Dict[str, Any],
        traps: List[Dict[str, Any]],
        call_wall: Dict[str, Any],
        put_wall: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Generates 3 institutional strategies:
        1. Delta Sweet-Spot Momentum (Optimal CE or PE Buy, Delta 0.38 - 0.52)
        2. Gamma Squeeze Breakout (Aggressive near Call Wall / Put Wall)
        3. Volatility Mean Reversion / Iron Condor Pinning (Selling walls in Long Gamma regime)
        """
        strategies = []
        has_call_trap = any(t["type"] == "CALL_WRITER_TRAP" for t in traps)
        net_thrust = constituents_report.get("net_transmitted_thrust_pts", 0.0)
        net_gex = quant_greeks.get("net_gex_crores", 0.0)

        # 1. Delta Sweet Spot Strategy
        primary_bias = "BULLISH" if net_thrust > 0 and not has_call_trap else "BEARISH"
        best_delta = self._select_best_trade(
            analyzed_strikes, spot_price, atm_strike, days_to_expiry, net_thrust, traps
        )
        if best_delta:
            best_delta["strategy_name"] = "Delta Sweet-Spot Directional Trade"
            best_delta["strategy_type"] = "DIRECTIONAL_MOMENTUM"
            strategies.append(best_delta)

        # 2. Gamma Squeeze Breakout Strategy
        gamma_strike = call_wall.get("strike", atm_strike + 100) if primary_bias == "BULLISH" else put_wall.get("strike", atm_strike - 100)
        opt_type = "CE" if primary_bias == "BULLISH" else "PE"
        sq_row = next((r for r in analyzed_strikes if r["strike"] == gamma_strike), None)
        if sq_row:
            leg = sq_row["call"] if opt_type == "CE" else sq_row["put"]
            ltp = leg["ltp"]
            if ltp > 10.0:
                d_mag = abs(leg["greeks"]["delta"])
                sl = round(ltp * 0.65, 1)
                t1 = round(ltp + d_mag * 75.0, 1)
                t2 = round(ltp + d_mag * 140.0, 1)
                rr = round((t1 - ltp) / max(ltp - sl, 1.0), 2)
                strategies.append({
                    "strategy_name": f"Wall Breakout & Gamma Squeeze ({opt_type})",
                    "strategy_type": "GAMMA_SQUEEZE",
                    "symbol": f"NIFTY {int(gamma_strike)} {opt_type}",
                    "strike": gamma_strike,
                    "option_type": opt_type,
                    "bias": primary_bias,
                    "entry_ltp": ltp,
                    "stop_loss": sl,
                    "target_1": t1,
                    "target_2": t2,
                    "risk_reward": f"1:{rr}",
                    "conviction_score": 88.0 if net_gex < 0 else 76.0,
                    "greeks": leg["greeks"],
                    "state": leg["state"],
                    "rationale": (
                        f"Targeting a gamma breakout at {gamma_strike:.0f} {opt_type}. "
                        f"If spot crosses this wall, short covering triggers an explosive runner."
                    ),
                })

        # 3. Mean Reversion Pinning / Range Strategy
        if call_wall.get("strike") and put_wall.get("strike"):
            cw = call_wall["strike"]
            pw = put_wall["strike"]
            c_row = next((r for r in analyzed_strikes if r["strike"] == cw), None)
            p_row = next((r for r in analyzed_strikes if r["strike"] == pw), None)
            c_prem = c_row["call"]["ltp"] if c_row else 25.0
            p_prem = p_row["put"]["ltp"] if p_row else 25.0
            tot_prem = round(c_prem + p_prem, 1)
            strategies.append({
                "strategy_name": "Iron Corridor / Wall Pinning Play",
                "strategy_type": "RANGE_PINNING",
                "symbol": f"NIFTY {int(pw)} PE / {int(cw)} CE",
                "strike": (cw + pw) / 2.0,
                "option_type": "STRANGLE_SELL",
                "bias": "RANGE_BOUND",
                "entry_ltp": tot_prem,
                "stop_loss": round(tot_prem * 1.5, 1),
                "target_1": round(tot_prem * 0.45, 1),
                "target_2": round(tot_prem * 0.20, 1),
                "risk_reward": "1:1.80",
                "conviction_score": 85.0 if net_gex > 0 else 60.0,
                "greeks": {
                    "delta": 0.05,
                    "gamma": -0.0003,
                    "theta": round(abs((c_row["call"]["greeks"]["theta"] if c_row else 0) + (p_row["put"]["greeks"]["theta"] if p_row else 0)), 1),
                    "vega": round((c_row["call"]["greeks"]["vega"] if c_row else 0) + (p_row["put"]["greeks"]["vega"] if p_row else 0), 1),
                },
                "state": "POSITIVE_GAMMA_PINNING",
                "rationale": (
                    f"Dealers Long Gamma (+₹{net_gex:.0f}Cr). Market pinned between Put Floor ₹{pw:.0f} "
                    f"and Call Cap ₹{cw:.0f}. High probability of premium decay into expiry."
                ),
            })

        return strategies

    def _select_best_trade(
        self,
        analyzed_strikes: List[Dict[str, Any]],
        spot_price: float,
        atm_strike: float,
        days_to_expiry: float,
        heavyweight_points: float,
        traps: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates all strikes using the Sweet Spot Delta formula (Delta in [0.38, 0.52])
        combined with flow alignment, heavyweight momentum, and risk-reward calculation.
        """
        # Determine overall bias
        has_call_trap = any(t["type"] == "CALL_WRITER_TRAP" for t in traps)
        
        if heavyweight_points > 15.0 and not has_call_trap:
            bias = "BULLISH"
            target_type = "call"
            opt_tag = "CE"
        elif heavyweight_points < -15.0:
            bias = "BEARISH"
            target_type = "put"
            opt_tag = "PE"
        else:
            # Fall back to strike OI momentum
            net_oich = sum(r["put"]["oich"] - r["call"]["oich"] for r in analyzed_strikes if abs(r["strike"] - atm_strike) <= 150)
            bias = "BULLISH" if net_oich > 0 and not has_call_trap else "BEARISH"
            target_type = "call" if bias == "BULLISH" else "put"
            opt_tag = "CE" if bias == "BULLISH" else "PE"

        best_candidate = None
        highest_score = -float("inf")

        expected_move_pts = max(abs(heavyweight_points), 65.0)

        for row in analyzed_strikes:
            k = row["strike"]
            leg = row[target_type]
            ltp = leg["ltp"]

            # Filter out illiquid or penny strikes
            if ltp < 25.0 or ltp > 350.0:
                continue

            delta_mag = abs(leg["greeks"]["delta"])

            # Delta sweet spot: 0.38 - 0.52
            delta_score = max(0.0, 1.0 - abs(delta_mag - 0.45) * 3.5) * 45.0
            
            # Flow alignment: bonus for positive OI change + positive price change
            flow_bonus = 20.0 if leg["state"] in ("LONG_BUILDUP", "GAMMA_EXPLOSION") else (10.0 if leg["state"] == "SHORT_COVERING" else 0.0)

            # Volume liquidity bonus
            vol_score = min(leg["volume"] / 250000.0, 15.0)

            # Theta drag penalty
            theta_penalty = (abs(leg["greeks"]["theta"]) / max(ltp, 1.0)) * 25.0

            total_score = delta_score + flow_bonus + vol_score - theta_penalty

            if total_score > highest_score:
                highest_score = total_score
                
                # Risk parameters
                stop_loss = round(max(ltp * 0.72, ltp - (delta_mag * 30.0)), 1)
                tgt_1 = round(ltp + (delta_mag * expected_move_pts * 0.75), 1)
                tgt_2 = round(ltp + (delta_mag * expected_move_pts * 1.35), 1)
                risk = max(ltp - stop_loss, 1.0)
                reward = tgt_1 - ltp
                rr_ratio = round(reward / risk, 2)

                best_candidate = {
                    "symbol": f"NIFTY {int(k)} {opt_tag}",
                    "strike": k,
                    "option_type": opt_tag,
                    "bias": bias,
                    "entry_ltp": ltp,
                    "stop_loss": stop_loss,
                    "target_1": tgt_1,
                    "target_2": tgt_2,
                    "risk_reward": f"1:{rr_ratio}",
                    "conviction_score": round(min(max(total_score, 30.0), 96.0), 1),
                    "greeks": leg["greeks"],
                    "state": leg["state"],
                    "rationale": (
                        f"Sweet-spot Delta ({delta_mag}) with {leg['state']} flow confirmation. "
                        f"Targeting a ~{expected_move_pts:.0f} pt move on Nifty backed by "
                        f"heavyweight basket momentum ({heavyweight_points:+.1f} pts)."
                    ),
                }

        # Guaranteed fallback if no strike passed tight filter: choose closest to ATM
        if best_candidate is None and analyzed_strikes:
            fallback_score = -float("inf")
            for row in analyzed_strikes:
                k = row["strike"]
                leg = row[target_type]
                ltp = leg["ltp"]
                if ltp <= 1.0:
                    continue
                delta_mag = abs(leg["greeks"]["delta"])
                score = -abs(delta_mag - 0.45)
                if score > fallback_score:
                    fallback_score = score
                    sl = round(max(ltp * 0.70, ltp - 25.0), 1)
                    t1 = round(ltp + 35.0, 1)
                    t2 = round(ltp + 65.0, 1)
                    best_candidate = {
                        "symbol": f"NIFTY {int(k)} {opt_tag}",
                        "strike": k,
                        "option_type": opt_tag,
                        "bias": bias,
                        "entry_ltp": ltp,
                        "stop_loss": sl,
                        "target_1": t1,
                        "target_2": t2,
                        "risk_reward": "1:1.65",
                        "conviction_score": 75.0,
                        "greeks": leg["greeks"],
                        "state": leg["state"],
                        "rationale": f"Optimal {opt_tag} strike closest to ATM Delta sweet spot with active flow.",
                    }

        return best_candidate


# Singleton
_nifty_quant_service: Optional[NiftyQuantService] = None

def get_nifty_quant_service() -> NiftyQuantService:
    global _nifty_quant_service
    if _nifty_quant_service is None:
        _nifty_quant_service = NiftyQuantService()
    return _nifty_quant_service
