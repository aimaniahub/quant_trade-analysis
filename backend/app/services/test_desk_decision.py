"""
Unit tests for hardened desk decision (LICHSGFIN-style conflict).
Run: python -m app.services.test_desk_decision
"""

from app.services.desk_decision import get_final_bias_and_score, fuse_with_hardened_decision


def test_lichsgfin_conflict_case():
    """
    Spot 502, Long Buildup HIGH, OI PCR 0.66, Vol PCR 0.39,
    HTF BEARISH, Gamma BEARISH near ATM, IV flat, 15m MIXED.
    Must: score <= 58, action WAIT, not BUY.
    """
    data = {
        "htf_daily": "BEARISH",
        "oi_pcr": 0.66,
        "vol_pcr": 0.39,
        "atm_pcr": 0.70,
        "atm_call_buildup": "Long Buildup",
        "atm_put_buildup": "Short Covering",
        "buildup_strength": "HIGH",
        "gamma_wall": 500,
        "gamma_bias": "BEARISH",
        "max_pain": 510,
        "spot": 502,
        "iv_skew": 0.0,
        "straddle_change_pct": 0.0,
        "tech_15m": "MIXED",
        "volume_vs_avg": 1.0,
    }
    out = get_final_bias_and_score(data)
    assert out["max_score_cap"] == 58, out
    assert out["score"] <= 58, out
    assert out["action"] == "WAIT", out
    assert out["pcr_regime"] == "CALL_WRITING_CEILING", out
    assert out["side_preference"] in ("SHORT_PREFERRED", "NEUTRAL"), out
    assert out["skew_label"] == "FLAT", out
    assert out["entry_long"] is False, out
    # Lean still bullish so UI column is not empty (watchlist)
    assert out["lean_bias"] == "BULLISH" or out["bias"] == "BULLISH", out
    assert out.get("watch_long") is True, out
    assert "CONFLICTED" in out["conviction"] or out["conviction"].startswith("LOW"), out
    print("LICHSGFIN case OK:", out["score"], out["action"], out.get("lean_bias"), out["conviction"])


def test_aligned_long_allows_buy():
    data = {
        "htf_daily": "BULLISH",
        "oi_pcr": 1.35,
        "vol_pcr": 1.20,
        "atm_pcr": 1.25,
        "atm_call_buildup": "Long Buildup",
        "atm_put_buildup": "Short Covering",
        "buildup_strength": "HIGH",
        "gamma_wall": 500,
        "gamma_bias": "BULLISH",
        "max_pain": 510,
        "spot": 505,
        "iv_skew": 4.0,
        "straddle_change_pct": 5.0,
        "tech_15m": "BULLISH",
        "volume_vs_avg": 1.3,
    }
    out = get_final_bias_and_score(data)
    assert out["side_preference"] == "LONG_PREFERRED", out
    assert out["score"] >= 62, out
    assert out["action"] in ("BUY", "BUY_CAUTIOUS"), out
    assert out["entry_long"] is True, out
    print("Aligned long OK:", out["score"], out["action"])


def test_fuse_adapter():
    out = fuse_with_hardened_decision(
        {"quant_score": 60, "factors": ["x"]},
        buildup={
            "primary_state": "Long Buildup",
            "conviction": "HIGH",
            "bias": "BULLISH",
            "atm_band": [
                {
                    "is_atm": True,
                    "call": {"state": "Long Buildup", "strength": "Strong"},
                    "put": {"state": "Short Covering", "strength": "Moderate"},
                }
            ],
        },
        tech={
            "ok": True,
            "bias": "NEUTRAL",
            "htf": {"bias": "BEARISH", "ok": True},
            "intraday": {"bias": "NEUTRAL", "ema_stack": "MIXED", "volume_ratio": 1.0},
        },
        premium={"straddle_chg_pct": 0, "ok": True},
        pcr={
            "oi_pcr": 0.66,
            "volume_pcr": 0.39,
            "atm_ce_rel_vol": 0.5,
            "atm_ce_vol_share": 0.4,
        },
        greeks={"gamma_wall_strike": 500, "delta_bias": "BEARISH"},
        max_pain={"max_pain": 510},
        iv={"skew": 0.0},
        spot=502,
    )
    assert out["action"] == "WAIT", out
    assert out["quant_score"] <= 58, out
    assert out.get("lean_bias") == "BULLISH" or out.get("bias") == "BULLISH", out
    print("Fuse adapter OK:", out["quant_score"], out["action"], out.get("lean_bias"))


def test_volume_confirmed_soft_conflict_can_be_cautious():
    """Soft conflict (only PCR ceiling) + strong CE/stock vol → BUY_CAUTIOUS possible."""
    data = {
        "htf_daily": "NEUTRAL",
        "oi_pcr": 0.65,
        "vol_pcr": 0.50,
        "atm_call_buildup": "Long Buildup",
        "atm_put_buildup": "Short Covering",
        "buildup_strength": "HIGH",
        "gamma_wall": 600,
        "gamma_bias": "NEUTRAL",
        "max_pain": 510,
        "spot": 502,
        "iv_skew": 0.0,
        "straddle_change_pct": 2.0,
        "tech_15m": "BULLISH",
        "volume_vs_avg": 1.4,
        "atm_ce_rel_vol": 2.0,
        "atm_ce_vol_share": 0.65,
        "band_ce_vol_share": 0.60,
        "ce_vol_share": 0.58,
    }
    out = get_final_bias_and_score(data)
    assert out["lean_bias"] == "BULLISH", out
    # Soft conflict only (not HTF bear) — volume can rescue to cautious buy
    assert out["action"] in ("BUY_CAUTIOUS", "WAIT"), out
    if out["action"] == "BUY_CAUTIOUS":
        assert out["vol_confirm_long"] is True, out
    print("Volume soft-conflict OK:", out["score"], out["action"], out.get("vol_confirm_long"))


if __name__ == "__main__":
    test_lichsgfin_conflict_case()
    test_aligned_long_allows_buy()
    test_fuse_adapter()
    test_volume_confirmed_soft_conflict_can_be_cautious()
    print("ALL TESTS PASSED")
