"""Paper desk fill + P&L helpers."""

from app.services.lot_sizes import lot_size
from app.services.trade_watch import _extract_json, _fill_trade, _pnl_fields


def test_lot_size_known():
    n, est = lot_size("NSE:SBIN-EQ")
    assert n == 750 and est is False


def test_lot_size_default():
    n, est = lot_size("NSE:SOMEOBSCURE-EQ")
    assert n == 500 and est is True


def test_extract_json_fenced():
    obj = _extract_json('```json\n{"trades":[{"symbol":"NSE:SBIN-EQ"}]}\n```')
    assert obj and obj["trades"][0]["symbol"] == "NSE:SBIN-EQ"


def test_fill_and_pnl():
    chains = {
        "NSE:SBIN-EQ": {
            "symbol": "NSE:SBIN-EQ",
            "spot": 800,
            "atm": 800,
            "legs": [
                {
                    "k": 800,
                    "ce": {"ltp": 18.5, "oi": 10000, "vol": 5000, "sym": "NSE:SBIN25SEP800CE"},
                    "pe": {"ltp": 12.0, "oi": 8000, "vol": 2000, "sym": "NSE:SBIN25SEP800PE"},
                }
            ],
        }
    }
    t = _fill_trade(
        {"symbol": "NSE:SBIN-EQ", "side": "CE", "strike": 800, "thesis": "OR break", "sl_premium": 12, "tp_premium": 28},
        chains,
    )
    assert t is not None
    assert t["qty_lots"] == 1
    assert t["entry"] == 18.5
    assert t["lot_size"] == 750
    assert t["notional"] == 18.5 * 750
    _pnl_fields(t, 22.0)
    assert t["pnl"] == round((22.0 - 18.5) * 750, 2)
    assert t["pnl_pct"] > 0


def test_fill_rejects_unknown_strike():
    chains = {"NSE:SBIN-EQ": {"legs": [{"k": 800, "ce": {"ltp": 18.5}, "pe": {"ltp": 10}}]}}
    t = _fill_trade({"symbol": "NSE:SBIN-EQ", "side": "CE", "strike": 9999}, chains)
    assert t is None
