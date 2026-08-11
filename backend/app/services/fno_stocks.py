"""
F&O Stocks List

Complete list of NSE F&O-eligible stocks.
These are stocks that have derivatives (futures and options) trading on NSE.
"""

from typing import List


# NSE F&O Stocks - Updated January 2026
# Format: "NSE:SYMBOL-EQ" for Fyers API compatibility
FNO_STOCKS: List[str] = [
    # Banking & Financial Services
    "NSE:HDFCBANK-EQ",
    "NSE:ICICIBANK-EQ",
    "NSE:SBIN-EQ",
    "NSE:KOTAKBANK-EQ",
    "NSE:AXISBANK-EQ",
    "NSE:INDUSINDBK-EQ",
    "NSE:BANKBARODA-EQ",
    "NSE:PNB-EQ",
    "NSE:FEDERALBNK-EQ",
    "NSE:IDFCFIRSTB-EQ",
    "NSE:BANDHANBNK-EQ",
    "NSE:AUBANK-EQ",
    "NSE:CANBK-EQ",
    "NSE:RBLBANK-EQ",
    
    # NBFC & Finance
    "NSE:BAJFINANCE-EQ",
    "NSE:BAJAJFINSV-EQ",
    # Note: NSE:HDFC-EQ delisted after HDFC–HDFCBANK merger — do not include
    "NSE:LICHSGFIN-EQ",
    "NSE:CHOLAFIN-EQ",
    "NSE:MANAPPURAM-EQ",
    "NSE:MUTHOOTFIN-EQ",
    "NSE:PFC-EQ",
    "NSE:RECLTD-EQ",
    "NSE:SBICARD-EQ",
    "NSE:SBILIFE-EQ",
    "NSE:HDFCLIFE-EQ",
    "NSE:ICICIPRULI-EQ",
    "NSE:ICICIGI-EQ",
    
    # IT & Technology
    "NSE:TCS-EQ",
    "NSE:INFY-EQ",
    "NSE:WIPRO-EQ",
    "NSE:HCLTECH-EQ",
    "NSE:TECHM-EQ",
    "NSE:LTIM-EQ",
    "NSE:MPHASIS-EQ",
    "NSE:COFORGE-EQ",
    "NSE:PERSISTENT-EQ",
    "NSE:LTTS-EQ",
    "NSE:OFSS-EQ",
    
    # Oil & Gas
    "NSE:RELIANCE-EQ",
    "NSE:ONGC-EQ",
    "NSE:IOC-EQ",
    "NSE:BPCL-EQ",
    "NSE:HINDPETRO-EQ",
    "NSE:GAIL-EQ",
    "NSE:PETRONET-EQ",
    "NSE:IGL-EQ",
    "NSE:MGL-EQ",
    "NSE:GUJGASLTD-EQ",
    
    # Metals & Mining
    "NSE:TATASTEEL-EQ",
    "NSE:JSWSTEEL-EQ",
    "NSE:HINDALCO-EQ",
    "NSE:VEDL-EQ",
    "NSE:COALINDIA-EQ",
    "NSE:NMDC-EQ",
    "NSE:NATIONALUM-EQ",
    "NSE:JINDALSTEL-EQ",
    "NSE:SAIL-EQ",
    "NSE:APLAPOLLO-EQ",
    
    # Automobiles
    "NSE:MARUTI-EQ",
    "NSE:TMPV-EQ",
    "NSE:M&M-EQ",
    "NSE:BAJAJ-AUTO-EQ",
    "NSE:HEROMOTOCO-EQ",
    "NSE:EICHERMOT-EQ",
    "NSE:ASHOKLEY-EQ",
    "NSE:TVSMOTOR-EQ",
    "NSE:ESCORTS-EQ",
    "NSE:MRF-EQ",
    "NSE:BALKRISIND-EQ",
    "NSE:APOLLOTYRE-EQ",
    "NSE:EXIDEIND-EQ",
    "NSE:AMARAJABAT-EQ",
    "NSE:MOTHERSON-EQ",
    "NSE:BOSCHLTD-EQ",
    
    # Pharma & Healthcare
    "NSE:SUNPHARMA-EQ",
    "NSE:DRREDDY-EQ",
    "NSE:CIPLA-EQ",
    "NSE:DIVISLAB-EQ",
    "NSE:BIOCON-EQ",
    "NSE:AUROPHARMA-EQ",
    "NSE:LUPIN-EQ",
    "NSE:ZYDUSLIFE-EQ",
    "NSE:TORNTPHARM-EQ",
    "NSE:ALKEM-EQ",
    "NSE:LAURUSLABS-EQ",
    "NSE:IPCALAB-EQ",
    "NSE:GLENMARK-EQ",
    "NSE:APOLLOHOSP-EQ",
    "NSE:FORTIS-EQ",
    "NSE:MAXHEALTH-EQ",
    
    # FMCG
    "NSE:HINDUNILVR-EQ",
    "NSE:ITC-EQ",
    "NSE:NESTLEIND-EQ",
    "NSE:BRITANNIA-EQ",
    "NSE:DABUR-EQ",
    "NSE:MARICO-EQ",
    "NSE:GODREJCP-EQ",
    "NSE:COLPAL-EQ",
    "NSE:TATACONSUM-EQ",
    "NSE:VBL-EQ",
    "NSE:UBL-EQ",
    "NSE:MCDOWELL-N-EQ",
    "NSE:PIDILITIND-EQ",
    "NSE:BERGEPAINT-EQ",
    "NSE:ASIANPAINT-EQ",
    
    # Cement & Building Materials
    "NSE:ULTRACEMCO-EQ",
    "NSE:SHREECEM-EQ",
    "NSE:AMBUJACEM-EQ",
    "NSE:ACC-EQ",
    "NSE:DALBHARAT-EQ",
    "NSE:RAMCOCEM-EQ",
    "NSE:GRASIM-EQ",
    
    # Power & Utilities
    "NSE:NTPC-EQ",
    "NSE:POWERGRID-EQ",
    "NSE:ADANIGREEN-EQ",
    "NSE:ADANIPOWER-EQ",
    "NSE:TATAPOWER-EQ",
    "NSE:JSWENERGY-EQ",
    "NSE:TORNTPOWER-EQ",
    "NSE:NHPC-EQ",
    "NSE:SJVN-EQ",
    
    # Infrastructure & Construction
    "NSE:LT-EQ",
    "NSE:ADANIENT-EQ",
    "NSE:ADANIPORTS-EQ",
    "NSE:DLF-EQ",
    "NSE:GODREJPROP-EQ",
    "NSE:OBEROIRLTY-EQ",
    "NSE:PRESTIGE-EQ",
    "NSE:LODHA-EQ",
    "NSE:BRIGADE-EQ",
    "NSE:GMRAIRPORT-EQ",
    "NSE:IRCON-EQ",
    "NSE:IRFC-EQ",
    
    # Telecom & Media
    "NSE:BHARTIARTL-EQ",
    "NSE:IDEA-EQ",
    "NSE:INDUSTOWER-EQ",
    "NSE:TATACOMM-EQ",
    "NSE:ZEEL-EQ",
    "NSE:PVRINOX-EQ",
    
    # Consumer Durables & Electronics
    "NSE:TITAN-EQ",
    "NSE:HAVELLS-EQ",
    "NSE:VOLTAS-EQ",
    "NSE:BATAINDIA-EQ",
    "NSE:PAGEIND-EQ",
    "NSE:CROMPTON-EQ",
    "NSE:DIXON-EQ",
    "NSE:WHIRLPOOL-EQ",
    "NSE:BLUESTARCO-EQ",
    
    # Engineering & Capital Goods
    "NSE:SIEMENS-EQ",
    "NSE:ABB-EQ",
    "NSE:CUMMINSIND-EQ",
    "NSE:THERMAX-EQ",
    "NSE:BHEL-EQ",
    "NSE:HAL-EQ",
    "NSE:BEL-EQ",
    "NSE:RAILTEL-EQ",
    "NSE:RVNL-EQ",
    
    # Chemicals & Fertilizers
    "NSE:UPL-EQ",
    "NSE:ATUL-EQ",
    "NSE:DEEPAKNTR-EQ",
    "NSE:NAVINFLUOR-EQ",
    "NSE:GNFC-EQ",
    "NSE:COROMANDEL-EQ",
    "NSE:SRF-EQ",
    "NSE:PIIND-EQ",
    "NSE:AARTIIND-EQ",
    "NSE:TATACHEM-EQ",
    
    # Miscellaneous
    "NSE:INDIGO-EQ",
    "NSE:DMART-EQ",
    "NSE:TRENT-EQ",
    "NSE:NYKAA-EQ",
    "NSE:ZOMATO-EQ",
    "NSE:PAYTM-EQ",
    "NSE:POLICYBZR-EQ",
    "NSE:IRCTC-EQ",
    "NSE:INDHOTEL-EQ",
    "NSE:JUBLFOOD-EQ",
    "NSE:MANYAVAR-EQ",
    "NSE:TATAELXSI-EQ",
    "NSE:POLYCAB-EQ",
    "NSE:KEI-EQ",
    "NSE:ASTRAL-EQ",
    "NSE:SUPREMEIND-EQ",
    "NSE:CUB-EQ",
]


# Popular high-volume F&O stocks (subset for quick scanning)
# Extended to 30 bluechip stocks for comprehensive coverage
TOP_FNO_STOCKS: List[str] = [
    # Heavyweights
    "NSE:RELIANCE-EQ",
    "NSE:TCS-EQ",
    "NSE:HDFCBANK-EQ",
    "NSE:ICICIBANK-EQ",
    "NSE:INFY-EQ",
    "NSE:HINDUNILVR-EQ",
    "NSE:SBIN-EQ",
    "NSE:BHARTIARTL-EQ",
    "NSE:ITC-EQ",
    "NSE:KOTAKBANK-EQ",
    # Large-Cap Banking
    "NSE:AXISBANK-EQ",
    "NSE:BAJFINANCE-EQ",
    "NSE:BAJAJFINSV-EQ",
    "NSE:INDUSINDBK-EQ",
    # Large-Cap Auto
    "NSE:MARUTI-EQ",
    "NSE:TMPV-EQ",
    "NSE:M&M-EQ",
    # Large-Cap IT
    "NSE:WIPRO-EQ",
    "NSE:HCLTECH-EQ",
    "NSE:TECHM-EQ",
    # Large-Cap Pharma
    "NSE:SUNPHARMA-EQ",
    "NSE:DRREDDY-EQ",
    "NSE:CIPLA-EQ",
    # Large-Cap Energy/Infra
    "NSE:NTPC-EQ",
    "NSE:POWERGRID-EQ",
    "NSE:LT-EQ",
    "NSE:ADANIENT-EQ",
    "NSE:ADANIPORTS-EQ",
    # Large-Cap Metals/FMCG
    "NSE:TATASTEEL-EQ",
    "NSE:TITAN-EQ",
    "NSE:ASIANPAINT-EQ",
]


# Index symbols commonly scanned alongside equities
FNO_INDICES: List[str] = [
    "NSE:NIFTY50-INDEX",
    "NSE:NIFTYBANK-INDEX",
    # Fyers symbol for Fin Nifty (not NIFTYFIN-INDEX)
    "NSE:FINNIFTY-INDEX",
]

# Runtime / known-bad symbols (auto-extended when Fyers returns Invalid symbol)
INVALID_SYMBOLS: set[str] = {
    "NSE:TATAMOTORS-EQ",  # demerged → use NSE:TMPV-EQ
    "NSE:NIFTYFIN-INDEX",  # wrong ticker → use NSE:FINNIFTY-INDEX
    "NSE:HDFC-EQ",
}


def is_valid_symbol(symbol: str) -> bool:
    return bool(symbol) and symbol not in INVALID_SYMBOLS


def mark_invalid_symbol(symbol: str) -> None:
    if symbol:
        INVALID_SYMBOLS.add(symbol)


def filter_valid_symbols(symbols: List[str]) -> List[str]:
    return [s for s in symbols if is_valid_symbol(s)]


def get_fno_stocks(top_only: bool = False) -> List[str]:
    """
    Get list of F&O stocks.
    
    Args:
        top_only: If True, return only top high-volume stocks
        
    Returns:
        List of stock symbols in Fyers format
    """
    return TOP_FNO_STOCKS if top_only else FNO_STOCKS


def get_fno_universe(include_indices: bool = True) -> List[str]:
    """Canonical scan universe used by MA / radar / scanners."""
    if include_indices:
        return list(dict.fromkeys([*FNO_STOCKS, *FNO_INDICES]))
    return list(FNO_STOCKS)


def get_stock_count() -> int:
    """Get total count of F&O stocks."""
    return len(FNO_STOCKS)
