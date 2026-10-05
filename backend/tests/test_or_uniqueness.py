"""Opening-range last-session + uniqueness ranking tests."""
from datetime import datetime, timedelta

from app.services.chain_anomaly import (
    UNIQUE_SCORE_FLOOR,
    apply_universe_rank,
    cap_screen_by_tag,
    opening_range_from_candles,
    opening_range_signal,
    screen_flags,
    BIAS_BULL,
    GRADE_TRADEABLE,
    GRADE_WATCH,
)


def _bar(dt: datetime, high: float, low: float, close: float) -> dict:
    return {
        "datetime": dt.isoformat(),
        "timestamp": dt.timestamp(),
        "high": high,
        "low": low,
        "close": close,
        "open": close,
        "volume": 1000,
    }


def test_opening_range_uses_last_session_on_weekend():
    friday = datetime(2026, 9, 4, 9, 15)  # Friday
    bars = [
        _bar(friday, 110, 100, 108),
        _bar(friday + timedelta(minutes=14), 112, 101, 111),
    ]
    sat = datetime(2026, 9, 5, 12, 0)
    sess = opening_range_from_candles(bars, now=sat)
    assert sess["valid"] is True
    assert sess["orh"] == 112
    assert sess["orl"] == 100
    assert sess["session_date"] == "2026-09-04"


def test_opening_range_wait_before_930():
    d = datetime(2026, 9, 4, 9, 20)
    bars = [_bar(datetime(2026, 9, 4, 9, 15), 110, 100, 108)]
    sess = opening_range_from_candles(bars, now=d)
    assert sess["orh"] == 110
    assert sess["valid"] is False


def test_or_break_needs_fuel_and_room():
    now = datetime(2026, 9, 4, 9, 40)
    bars = [
        _bar(datetime(2026, 9, 4, 9, 15), 110, 100, 108),
        _bar(datetime(2026, 9, 4, 9, 20), 112, 101, 111),
    ]
    anoms, sess = opening_range_signal(
        spot=120,
        candles=bars,
        anomalies=[],
        structure={"call_wall": 121, "put_wall": 90, "gamma_wall": None, "max_pain": 100},
        atr=10.0,
        now=now,
    )
    assert sess["break_state"] == "OR_BREAK_LONG"
    assert sess["confirmed"] is False
    assert "premium" in (sess.get("reason") or "").lower() or "OI" in (sess.get("reason") or "")
    assert anoms == []


def test_or_break_confirms_with_fuel_and_room():
    now = datetime(2026, 9, 4, 9, 40)
    bars = [
        _bar(datetime(2026, 9, 4, 9, 15), 110, 100, 108),
        _bar(datetime(2026, 9, 4, 9, 20), 112, 101, 111),
    ]
    fuel = {
        "side": "CE",
        "direction": BIAS_BULL,
        "exhaustion": False,
        "ltp_chg_pct": 4.0,
        "oi_added": 40000,
        "oi_change_pct": 20,
        "volume": 80000,
        "ltp": 45,
        "strike": 115,
        "oi": 100000,
        "vor": 0.8,
        "atm_dist_pct": 1.0,
    }
    anoms, sess = opening_range_signal(
        spot=120,
        candles=bars,
        anomalies=[fuel],
        structure={"call_wall": 140, "put_wall": 90, "gamma_wall": None, "max_pain": 100},
        atr=10.0,
        now=now,
    )
    assert sess["confirmed"] is True
    assert anoms and anoms[0]["type"] == "OR_BREAK_LONG"


def test_screen_flags_do_not_tag_static_walls():
    flags = screen_flags({
        "grade": GRADE_WATCH,
        "chain_bias": BIAS_BULL,
        "setup_score": 40,
        "anomalies": [],
        "structure": {
            "put_wall": 100,
            "call_wall": 120,
            "near_put_wall": True,
            "put_wall_dominant": True,
            "oi_pcr": 1.4,
            "iv_skew": 0.2,
            "buildup": {"primary_state": "Quiet"},
        },
        "spot": 101,
        "volume": {"total_volume": 5000, "hottest_vol_x": 1.1, "vs_avg": 1.0},
        "futures": {"state": "NEUTRAL"},
        "symbol": "NSE:XYZ-EQ",
        "max_oi_added": 100,
    })
    assert flags["support"] is False
    assert flags["resistance"] is False
    assert flags["early_mover"] is False
    assert "SUPPORT" not in flags["tags"]


def test_universe_rank_marks_top_tail_unique():
    hits = []
    for i in range(20):
        hits.append({
            "symbol": f"S{i}",
            "bucket": "REST",
            "grade": GRADE_TRADEABLE if i > 16 else GRADE_WATCH,
            "setup_score": i * 5,
            "flags": {
                "oi_added": i * 1000,
                "vor": i / 20.0,
                "vol_x": 1 + i / 10.0,
                "tags": ["CALL_BUYING"] if i > 10 else ["WATCH"],
            },
        })
    apply_universe_rank(hits)
    unique = [h for h in hits if (h.get("flags") or {}).get("unique")]
    assert unique, "expected a unique tail"
    assert all((h["flags"]["unique_score"] >= UNIQUE_SCORE_FLOOR) for h in unique)
    capped = cap_screen_by_tag(hits, cap=3)
    assert len(capped) <= 6
