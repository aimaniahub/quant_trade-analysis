"""VWAP + option-chain process gate — Pure trades can print."""

from __future__ import annotations

from datetime import datetime

from app.services.idea_engine import (
    FlowSnapshot,
    evaluate_candidate,
    vwap_confirmation,
)
from app.utils.market_hours import IST

NOW = IST.localize(datetime(2026, 8, 17, 11, 15, 0))


def _snap(ts: float, **kw) -> FlowSnapshot:
    base = dict(
        ts=ts,
        symbol="NSE:SBIN-EQ",
        direction="BULLISH",
        strike=830.0,
        opt_type="CE",
        label="Fresh Call Buying",
        signal="BULLISH",
        lis=62.0,
        grade="A",
        composite_raw=70.0,
        unusual_score=22.0,
        atm_dist_pct=1.2,
        delta=0.45,
        dte=10.0,
        opposing=False,
        spot=831.0,
        oi_change_pct=18.0,
        vol_spike_ratio=2.1,
        premium_notional=1.2e6,
    )
    base.update(kw)
    return FlowSnapshot(**base)


def _map(*, vwap: float = 820.0, mtf=None, futures=None) -> dict:
    return {
        "day": {"ok": False},
        "session": {"vwap": vwap, "vwap_side": "VWAP_ABOVE" if 831 >= vwap else "VWAP_BELOW"},
        "structure": {"put_wall": 800, "call_wall": 860, "pcr": 1.05, "pcr_bias": "NEUTRAL"},
        "futures": futures or {"state": "LONG_BUILDUP", "agree_long": True, "agree_short": False},
        "mtf": mtf or {},
        "chain": [],
    }


def _ring(direction: str = "BULLISH") -> list:
    t0 = NOW.timestamp() - 200
    t1 = NOW.timestamp() - 10
    return [
        _snap(t0, direction=direction, spot=830.0 if direction == "BULLISH" else 818.0),
        _snap(t1, direction=direction, spot=831.0 if direction == "BULLISH" else 817.0),
    ]


def test_vwap_confirmation_sides():
    assert vwap_confirmation(831, {"vwap": 820}, "BULLISH")["agree"] is True
    assert vwap_confirmation(810, {"vwap": 820}, "BULLISH")["agree"] is False
    assert vwap_confirmation(810, {"vwap": 820}, "BEARISH")["agree"] is True
    assert vwap_confirmation(831, {"vwap": 820}, "BEARISH")["agree"] is False
    near = vwap_confirmation(820.1, {"vwap": 820}, "BEARISH")
    assert near["near"] is True
    assert near["agree"] is True


def test_vwap_oc_promotes_when_4h_mixed():
    snaps = _ring("BULLISH")
    ev = evaluate_candidate(
        snap=snaps[-1],
        snapshots=snaps,
        full_map=_map(vwap=820, mtf={"allowed_side": "NONE", "h4_bias": "MIXED", "confirmed_ready": False}),
        now=NOW,
    )
    assert ev["vwap_oc_ready"] is True
    assert "VWAP_OPPOSE" not in ev["vetoes"]
    assert "MTF_NOT_READY" not in ev["vetoes"]
    assert "MTF_SIDE_BLOCK" not in ev["vetoes"]
    assert ev["can_promote"] is True
    assert ev["recipe"]["id"] == "VWAP_OC"


def test_vwap_oc_promotes_watch_long_without_15m_trigger():
    snaps = _ring("BULLISH")
    ev = evaluate_candidate(
        snap=snaps[-1],
        snapshots=snaps,
        full_map=_map(
            vwap=820,
            mtf={
                "allowed_side": "LONG",
                "h4_bias": "BULLISH",
                "confirmed_ready": False,
                "hq_pullback": False,
                "campaign": "WATCH",
            },
        ),
        now=NOW,
    )
    assert ev["can_promote"] is True
    assert "MTF_NOT_READY" not in ev["vetoes"]


def test_4h_opposite_still_blocks():
    snaps = _ring("BULLISH")
    ev = evaluate_candidate(
        snap=snaps[-1],
        snapshots=snaps,
        full_map=_map(
            vwap=820,
            mtf={"allowed_side": "SHORT", "h4_bias": "BEARISH", "confirmed_ready": True},
        ),
        now=NOW,
    )
    assert "MTF_SIDE_BLOCK" in ev["vetoes"]
    assert ev["can_promote"] is False


def test_wrong_side_of_vwap_blocks():
    snaps = _ring("BULLISH")
    ev = evaluate_candidate(
        snap=snaps[-1],
        snapshots=snaps,
        full_map=_map(vwap=860, mtf={"allowed_side": "LONG", "h4_bias": "BULLISH"}),
        now=NOW,
    )
    assert ev["vwap"]["agree"] is False
    assert "VWAP_OPPOSE" in ev["vetoes"]
    assert ev["can_promote"] is False


def test_bearish_below_vwap_promotes():
    snaps = _ring("BEARISH")
    for s in snaps:
        s.label = "Fresh Put Buying"
        s.signal = "BEARISH"
        s.opt_type = "PE"
    ev = evaluate_candidate(
        snap=snaps[-1],
        snapshots=snaps,
        full_map=_map(
            vwap=830,
            mtf={"allowed_side": "NONE", "h4_bias": "MIXED", "confirmed_ready": False},
            futures={"state": "SHORT_BUILDUP", "agree_long": False, "agree_short": True},
        ),
        now=NOW,
    )
    assert ev["vwap_oc_ready"] is True
    assert ev["can_promote"] is True


def test_idea_book_board_splits_pure_not_watch():
    from app.services.idea_book import IdeaBook

    book = IdeaBook(hydrate=False, persist=False)
    snaps = _ring("BULLISH")
    full = _map(vwap=820, mtf={"allowed_side": "NONE", "h4_bias": "MIXED", "confirmed_ready": False, "hq_pullback": False, "campaign": "NO_TRADE"})
    book.ingest(snaps[0], full, now=NOW)
    out = book.ingest(snaps[1], full, now=NOW)
    idea = out["idea"]
    assert idea["status"] == "ACTIVE"
    assert idea.get("hq_pullback") is False
    assert idea.get("campaign") == "CONFIRMED"
    assert idea.get("vwap_agree") is True
    board = book.board()
    assert board["counts"]["bullish"] == 1
    assert board["counts"]["pullbacks"] == 0
    assert board["bullish"][0]["symbol"] == "NSE:SBIN-EQ"


def test_single_print_stays_watch():
    snap = _snap(NOW.timestamp(), direction="BULLISH")
    ev = evaluate_candidate(
        snap=snap,
        snapshots=[snap],
        full_map=_map(vwap=820, mtf={"allowed_side": "NONE", "h4_bias": "MIXED"}),
        now=NOW,
    )
    assert ev["vwap_oc_ready"] is True
    assert ev["can_promote"] is False
    assert ev["persist"]["same"] == 1


if __name__ == "__main__":
    test_vwap_confirmation_sides()
    test_vwap_oc_promotes_when_4h_mixed()
    test_vwap_oc_promotes_watch_long_without_15m_trigger()
    test_4h_opposite_still_blocks()
    test_wrong_side_of_vwap_blocks()
    test_bearish_below_vwap_promotes()
    test_single_print_stays_watch()
    test_idea_book_board_splits_pure_not_watch()
    print("ok")
