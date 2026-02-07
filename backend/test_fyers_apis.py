from app.services.fyers_auth import get_auth_service
from app.services.fyers_market import get_market_service
import json

def test_apis():
    auth = get_auth_service()
    market = get_market_service()
    
    print("--- Testing Profile ---")
    fyers = auth.get_fyers_model()
    profile = fyers.get_profile()
    print(f"Profile Response: {profile}")
    
    print("\n--- Testing Quotes (Indices) ---")
    indices = ["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"]
    quotes = market.get_quotes(indices)
    print(f"Quotes Success: {quotes.get('success')}")
    if not quotes.get('success'):
        print(f"Quotes Error: {quotes.get('error')}")
    else:
        print(f"Quotes Data Count: {len(quotes.get('data', []))}")

    print("\n--- Testing Option Chain (NIFTY) ---")
    symbol = "NSE:NIFTY50-INDEX"
    try:
        data = {"symbol": symbol, "strikecount": 10}
        response = fyers.optionchain(data)
        print(f"Option Chain Response: {json.dumps(response, indent=2)}")
    except Exception as e:
        print(f"Option Chain Exception: {e}")

if __name__ == "__main__":
    test_apis()
