"""NSE F&O lot sizes for 1-lot paper P&L. Unknown names default to 500."""

from __future__ import annotations

from typing import Tuple

# Short name → lot. Keep majors current; rest fall back.
_LOTS = {
    "NIFTY50": 25,
    "NIFTY": 25,
    "NIFTYBANK": 15,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "RELIANCE": 250,
    "TCS": 175,
    "HDFCBANK": 550,
    "ICICIBANK": 700,
    "INFY": 400,
    "HINDUNILVR": 300,
    "SBIN": 750,
    "BHARTIARTL": 475,
    "ITC": 1600,
    "KOTAKBANK": 400,
    "AXISBANK": 625,
    "BAJFINANCE": 125,
    "BAJAJFINSV": 250,
    "INDUSINDBK": 700,
    "MARUTI": 50,
    "TMPV": 550,
    "M&M": 200,
    "WIPRO": 1500,
    "HCLTECH": 250,
    "TECHM": 300,
    "SUNPHARMA": 350,
    "DRREDDY": 125,
    "CIPLA": 325,
    "NTPC": 1500,
    "POWERGRID": 1300,
    "LT": 150,
    "ADANIENT": 300,
    "ADANIPORTS": 450,
    "TATASTEEL": 550,
    "TITAN": 175,
    "ASIANPAINT": 200,
    "ONGC": 1150,
    "COALINDIA": 1350,
    "JSWSTEEL": 675,
    "HINDALCO": 700,
    "VEDL": 1200,
    "TATAMOTORS": 550,
    "ULTRACEMCO": 100,
    "NESTLEIND": 80,
    "TITAN": 175,
}


def _short(symbol: str) -> str:
    part = (symbol or "").split(":")[-1]
    return part.replace("-EQ", "").replace("-INDEX", "").upper()


def lot_size(symbol: str) -> Tuple[int, bool]:
    """Return (lot, estimated). estimated=True when using the 500 default."""
    key = _short(symbol)
    if key in _LOTS:
        return int(_LOTS[key]), False
    return 500, True
