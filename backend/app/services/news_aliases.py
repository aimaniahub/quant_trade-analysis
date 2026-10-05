"""Map news names → NSE F&O symbols. Code-owned; the model cannot invent tickers."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from app.services.fno_stocks import FNO_INDICES, FNO_STOCKS, filter_valid_symbols, is_valid_symbol


def short_name(symbol: str) -> str:
    part = (symbol or "").split(":")[-1]
    return part.replace("-EQ", "").replace("-INDEX", "").upper()


def _auto_map() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for sym in filter_valid_symbols(list(FNO_STOCKS) + list(FNO_INDICES)):
        out[short_name(sym)] = sym
    return out


# Extra English / group-safe aliases. Values must exist in FNO_STOCKS or FNO_INDICES.
_EXTRA: Dict[str, str] = {
    "TATA CONSULTANCY": "NSE:TCS-EQ",
    "TATA CONSULTANCY SERVICES": "NSE:TCS-EQ",
    "HDFC BANK": "NSE:HDFCBANK-EQ",
    "ICICI BANK": "NSE:ICICIBANK-EQ",
    "STATE BANK": "NSE:SBIN-EQ",
    "STATE BANK OF INDIA": "NSE:SBIN-EQ",
    "KOTAK MAHINDRA": "NSE:KOTAKBANK-EQ",
    "KOTAK": "NSE:KOTAKBANK-EQ",
    "AXIS BANK": "NSE:AXISBANK-EQ",
    "BAJAJ FINANCE": "NSE:BAJFINANCE-EQ",
    "BAJAJ FINSERV": "NSE:BAJAJFINSV-EQ",
    "BHARTI AIRTEL": "NSE:BHARTIARTL-EQ",
    "AIRTEL": "NSE:BHARTIARTL-EQ",
    "INFOSYS": "NSE:INFY-EQ",
    "HINDUSTAN UNILEVER": "NSE:HINDUNILVR-EQ",
    "HUL": "NSE:HINDUNILVR-EQ",
    "LARSEN": "NSE:LT-EQ",
    "LARSEN AND TOUBRO": "NSE:LT-EQ",
    "L&T": "NSE:LT-EQ",
    "TATA STEEL": "NSE:TATASTEEL-EQ",
    "TATA POWER": "NSE:TATAPOWER-EQ",
    "TATA MOTORS": "NSE:TMPV-EQ",
    "TVS MOTOR": "NSE:TVSMOTOR-EQ",
    "TVS": "NSE:TVSMOTOR-EQ",
    "ASHOK LEYLAND": "NSE:ASHOKLEY-EQ",
    "MAHINDRA": "NSE:M&M-EQ",
    "M&M": "NSE:M&M-EQ",
    "MARUTI SUZUKI": "NSE:MARUTI-EQ",
    "RELIANCE INDUSTRIES": "NSE:RELIANCE-EQ",
    "ADANI ENTERPRISES": "NSE:ADANIENT-EQ",
    "ADANI PORTS": "NSE:ADANIPORTS-EQ",
    "NIFTY": "NSE:NIFTY50-INDEX",
    "NIFTY 50": "NSE:NIFTY50-INDEX",
    "NIFTY50": "NSE:NIFTY50-INDEX",
    "SENSEX": "NSE:NIFTY50-INDEX",
    "BANK NIFTY": "NSE:NIFTYBANK-INDEX",
    "NIFTY BANK": "NSE:NIFTYBANK-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "FINNIFTY": "NSE:FINNIFTY-INDEX",
    "INDIA VIX": "NSE:INDIAVIX-INDEX",
    "VIX": "NSE:INDIAVIX-INDEX",
}


_GROUP_SKIP = (
    "TATA GROUP",
    "ADANI GROUP",
    "ADANI",
    "TATA SONS",
)


def allow_map() -> Dict[str, str]:
    """short/alias → Fyers symbol. Invalid symbols dropped."""
    out = _auto_map()
    for k, v in _EXTRA.items():
        if is_valid_symbol(v) and (v in FNO_STOCKS or v in FNO_INDICES or v.endswith("-INDEX")):
            out[k.upper()] = v
    # India VIX may not be in FNO_STOCKS; still allow as index context only.
    out.setdefault("INDIAVIX", "NSE:INDIAVIX-INDEX")
    return out


def fno_short_names() -> List[str]:
    return sorted({short_name(s) for s in filter_valid_symbols(list(FNO_STOCKS) + list(FNO_INDICES))})


def is_index(symbol: str) -> bool:
    return "INDEX" in (symbol or "").upper() or (symbol or "").endswith("-INDEX")


def resolve_name(raw: str) -> Optional[str]:
    """Resolve a model/article name to a Fyers symbol, or None."""
    if not raw:
        return None
    key = " ".join(str(raw).replace("-EQ", "").replace("-INDEX", "").replace("NSE:", "").split()).upper()
    if not key or key in _GROUP_SKIP:
        return None
    mapping = allow_map()
    if key in mapping:
        return mapping[key]
    # compact form HDFC BANK → HDFCBANK
    compact = key.replace(" ", "").replace("&", "&")
    if compact in mapping:
        return mapping[compact]
    return None


def count_mentions(text: str, symbol: str) -> int:
    blob = (text or "").upper()
    if not blob:
        return 0
    names = [short_name(symbol)]
    for alias, sym in allow_map().items():
        if sym == symbol and alias not in names:
            names.append(alias)
    n = 0
    for name in names:
        if len(name) < 3:
            continue
        if name in blob:
            n += 1
    return n


def index_symbols() -> Tuple[str, ...]:
    return tuple(FNO_INDICES)
