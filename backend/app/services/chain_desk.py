"""
I/O adapter: stored chain + futures + prior digest → ChainReport.

Harvest and row-click call `evaluate`. This module does not hit Fyers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.services.chain_anomaly import analyze_chain, summarize_report
from app.services.trade_lock import get_trade_lock

logger = logging.getLogger(__name__)

NIFTY = "NSE:NIFTY50-INDEX"


def _store():
    from app.services import symbol_store as store

    return store


def _index_ctx(symbol: str) -> Optional[Dict[str, Any]]:
    if symbol == NIFTY or "NIFTY50" in (symbol or ""):
        return None
    try:
        doc = _store().get(NIFTY) or {}
        rep = (doc.get("anomaly") or {}).get("report") or doc.get("anomaly")
        if not isinstance(rep, dict) or not rep.get("chain_bias"):
            return None
        return {
            "bias": rep.get("chain_bias"),
            "grade": rep.get("grade"),
            "regime": (rep.get("structure") or {}).get("regime"),
        }
    except Exception:
        return None


def _peek_day_map(symbol: str) -> Dict[str, Any]:
    try:
        from app.services.levels import get_levels_service
        return get_levels_service().peek_day_map(symbol) or {}
    except Exception:
        return {}


def _htf(symbol: str) -> Dict[str, Any]:
    try:
        from app.services.mtf_service import get_mtf_service

        return get_mtf_service().evaluate(symbol) or {}
    except Exception as exc:
        logger.debug("htf %s: %s", symbol, exc)
        return {}


def evaluate(
    symbol: str,
    chain_resp: Dict[str, Any],
    *,
    name: Optional[str] = None,
    pass_id: Optional[str] = None,
) -> Dict[str, Any]:
    store = _store()
    snap = store.get(symbol) or {}
    chain = list(chain_resp.get("chain") or [])
    spot = float(
        chain_resp.get("spot_price")
        or (snap.get("spot") or {}).get("ltp")
        or 0
    )
    derived = snap.get("derived") or {}
    m15 = []
    try:
        m15 = store.get_history(symbol, "15", min_bars=8) or []
    except Exception:
        m15 = []

    vwap = derived.get("vwap")
    ema20 = derived.get("ema20_15") or derived.get("ema20")
    atr = derived.get("atr")

    prev_report = None
    prev_digest = None
    anomaly_doc = snap.get("anomaly") or {}
    if isinstance(anomaly_doc, dict):
        prev_report = anomaly_doc.get("report") or (
            anomaly_doc if anomaly_doc.get("grade") else None
        )
        prev_digest = anomaly_doc.get("digest") or (prev_report or {}).get("digest")

    snapshot = {
        "symbol": symbol,
        "name": name,
        "chain": chain,
        "spot": spot,
        "atm": chain_resp.get("atm_strike"),
        "expiries": chain_resp.get("expiries") or [],
        "futures": snap.get("futures") or {},
        "prev_digest": prev_digest or {},
        "prev_report": prev_report or {},
        "htf": _htf(symbol),
        "candles_15": m15,
        "vwap": vwap,
        "ema20": ema20,
        "atr": atr,
        "index_ctx": _index_ctx(symbol),
        "vix": (store.get("NSE:INDIAVIX-INDEX") or {}).get("spot"),
        "pass_id": pass_id,
        "day_map": _peek_day_map(symbol),
    }
    report = analyze_chain(snapshot)
    report = get_trade_lock().apply(report)
    summary = summarize_report(report)
    try:
        store.put(
            symbol,
            {
                "anomaly": {
                    "report": report,
                    "summary": summary,
                    "digest": report.get("digest") or {},
                    "grade": report.get("grade"),
                    "chain_bias": report.get("chain_bias"),
                    "ts": report.get("ts"),
                }
            },
        )
    except Exception as exc:
        logger.debug("persist anomaly %s: %s", symbol, exc)
    return report


def reevaluate_with_stored_futures(symbol: str) -> Optional[Dict[str, Any]]:
    store = _store()
    snap = store.get(symbol) or {}
    chain_body = snap.get("chain") or {}
    rows = chain_body.get("rows") or chain_body.get("chain") or []
    if len(rows) < 6:
        return None
    chain_resp = {
        "success": True,
        "chain": rows,
        "spot_price": chain_body.get("spot_price") or (snap.get("spot") or {}).get("ltp"),
        "atm_strike": chain_body.get("atm_strike"),
        "expiries": chain_body.get("expiries") or [],
    }
    pass_id = (snap.get("anomaly") or {}).get("report", {}).get("pass_id") if isinstance(snap.get("anomaly"), dict) else None
    return evaluate(symbol, chain_resp, name=(snap.get("name")), pass_id=pass_id)
