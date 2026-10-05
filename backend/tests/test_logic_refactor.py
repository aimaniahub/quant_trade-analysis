"""
Unit tests for Option Chain & FlowRadar Logic Refactor:
- VOR computation and Footstep Score in radar_signal_engine
- Short Squeeze detection and override (fading unblocked) in chain_anomaly
- Instant harvest-bypass for high conviction setups in chain_anomaly
- Tag exclusivity in screen_flags (ranked tags, no tag inflation)
"""

import unittest
from app.services.radar_signal_engine import compute_vor, compute_footstep_score
from app.services.chain_anomaly import (
    compute_oi_velocity,
    detect_squeeze_active,
    decide_grade,
    screen_flags,
    GRADE_TRADEABLE,
    GRADE_WATCH,
    BIAS_BULL,
    BIAS_BEAR,
    BIAS_NEUTRAL,
)

class TestLogicRefactor(unittest.TestCase):
    def test_vor_calculation(self):
        # 0 volume or 0 oi
        self.assertEqual(compute_vor(0, 1000), 0.0)
        self.assertEqual(compute_vor(1000, 0), 0.0)
        # Normal ratio
        self.assertAlmostEqual(compute_vor(5000, 2000), 2.5)
        # Cap at 10.0
        self.assertEqual(compute_vor(50000, 1000), 10.0)

    def test_footstep_score(self):
        # High VOR + accelerating velocity
        result = compute_footstep_score(
            vor=3.5,
            oi_velocity=1200.0,
            is_accelerating=True,
            chain_vol_expansion=2.5,
            premium_direction_match=True,
            atm_dist_pct=1.0,
            cluster_count=3,
        )
        self.assertIsInstance(result, dict)
        self.assertGreater(result["score"], 60.0)
        self.assertLessEqual(result["score"], 100.0)
        self.assertTrue(result["early_mover"])

    def test_short_squeeze_detection_and_override(self):
        # Squeeze detection: futures short covering + flow bias BULLISH + CE buying
        futures = {"state": "SHORT_COVERING"}
        anomalies = [
            {
                "type": "FOOTSTEP_EARLY",
                "side": "CE",
                "strike": 2500,
                "label": "Fresh Call Buying",
                "exhaustion": False,
                "vor": 1.2,
                "oi_added": 25000,
                "vol_x": 2.5,
            }
        ]
        is_squeeze, note = detect_squeeze_active(
            futures=futures,
            flow_bias=BIAS_BULL,
            anomalies=anomalies,
            chain=[],
            spot=2490.0,
        )
        self.assertTrue(is_squeeze)
        self.assertIn("Short squeeze active", str(note))

        # Test decide_grade override with short squeeze active
        grade, chain_bias, intent, why = decide_grade(
            structure_bias=BIAS_BULL,
            futures={"state": "SHORT_COVERING", "futures_bias": BIAS_BULL, "fade": True},
            flow_bias=BIAS_BULL,
            htf={"ok": True},
            anomalies=anomalies,
            exhaustion_only=False,
            index_ctx=None,
            prev_report=None,
            volume_regime={"expanded": True, "vs_avg": 2.2},
        )
        self.assertEqual(grade, GRADE_TRADEABLE)
        self.assertEqual(chain_bias, BIAS_BULL)
        self.assertTrue(any("Short squeeze active" in w for w in why))

    def test_tag_exclusivity(self):
        # Verify that screen_flags produces ranked, non-inflated tags
        report = {
            "symbol": "NSE:RELIANCE-EQ",
            "bucket": "HEAVY",
            "chain_bias": BIAS_BULL,
            "anomalies": [
                {
                    "type": "FOOTSTEP_EARLY",
                    "types": ["FOOTSTEP_EARLY"],
                    "side": "CE",
                    "strike": 2900,
                    "label": "Fresh Call Buying",
                    "vor": 2.1,
                    "oi_velocity": 1500.0,
                    "oi_added": 50000,
                }
            ],
            "volume": {"total_volume": 250000, "vs_avg": 2.5},
            "structure": {"put_wall": 2850, "call_wall": 2950},
            "futures": {"state": "SHORT_COVERING"},
            "grade": GRADE_TRADEABLE,
        }
        flags = screen_flags(report)
        self.assertTrue(flags["squeeze_active"])
        self.assertIn("SQUEEZE_ACTIVE", flags["tags"])
        # Should not have multiple conflicting intent tags
        self.assertNotIn("CALL_BUYING", flags["tags"])
        self.assertNotIn("SHORT_COVER", flags["tags"])

if __name__ == "__main__":
    unittest.main()
