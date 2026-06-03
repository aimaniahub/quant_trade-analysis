import asyncio
import sys
import os

# Set up paths for running standalone script
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "backend")))

from app.services.high_volume_scanner import get_scanner_service
from app.services.fno_intelligence import get_intelligence_engine

scanner_service = get_scanner_service()
intel_engine = get_intelligence_engine()

# Mock Chain Data
mock_chain_data = {
    "success": True,
    "symbol": "NSE:HDFCBANK-EQ",
    "spot_price": 1450.0,
    "atm_strike": 1450.0,
    "total_call_oi": 100000,
    "total_put_oi": 150000,
    "pcr": 1.5,
    "india_vix": 14.5,
    "chain": [
        {
            "strike_price": 1300.0,
            "call": {"oi": 5000, "volume": 1000, "ltp": 55.0},
            "put": {"oi": 40000, "volume": 150000, "ltp": 2.0},
        },
        {
            "strike_price": 1350.0,
            "call": {"oi": 5000, "volume": 1000, "ltp": 55.0},
            "put": {"oi": 40000, "volume": 150000, "ltp": 2.0},
        },
        {
            "strike_price": 1400.0,
            "call": {"oi": 5000, "volume": 1000, "ltp": 55.0},
            "put": {"oi": 40000, "volume": 150000, "ltp": 2.0},
        },
        {
            "strike_price": 1450.0,
            "call": {"oi": 20000, "volume": 50000, "ltp": 15.0},
            "put": {"oi": 30000, "volume": 170000, "ltp": 14.0},
        },
        {
            "strike_price": 1500.0,
            "call": {"oi": 50000, "volume": 280000, "ltp": 2.0},
            "put": {"oi": 10000, "volume": 8000, "ltp": 50.0},
        }
    ]
}

def test():
    print("Running Institutional Analysis Test...")
    
    # 1. Test FNO Intelligence
    intel_analysis = intel_engine.get_analysis_summary(mock_chain_data, bypass_time_check=True)
    print("\n[Intel Analysis]")
    print("State:", intel_analysis.get("state"))
    print("Tradable:", intel_analysis.get("tradable"))
    print("Strike Guidance:", intel_analysis.get("strike_guidance"))
    print("Institutional Flow:", intel_analysis.get("institutional_flow", {}))
    
    # 2. Test High Volume Scanner mapping
    oi_analysis = scanner_service._analyze_oi_concentrations(mock_chain_data, 1450.0)
    greeks_analysis = scanner_service._calculate_greeks_score(mock_chain_data)
    
    trade_rec = scanner_service._generate_trade_recommendation(
        "NSE:HDFCBANK-EQ", 1450.0, 1450.0,
        oi_analysis, greeks_analysis, intel_analysis
    )
    
    print("\n[Trade Recommendation Result]")
    import json
    with open("C:/tmp/test_result.json", "w") as f:
        json.dump(trade_rec, f, indent=2)
    print("Saved to C:/tmp/test_result.json")

if __name__ == "__main__":
    test()
