"""
Unit Tests for Enhanced VAT Strategy
-------------------------------------
Tests the Value Adjustment Theory implementation including:
- Gap calculation and scoring
- Confidence score calculation
- Expiry phase detection
- Trade parameter calculations
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio

# Import the strategy components
from app.services.strategies.vat import (
    EnhancedVATStrategy,
    VATConfig,
    VATSignal,
    ExpiryPhase,
    SignalStrength,
    MarketContext
)


class TestVATConfig:
    """Test VATConfig dataclass defaults."""
    
    def test_default_config(self):
        config = VATConfig()
        assert config.min_gap_nifty == 7.0
        assert config.min_gap_banknifty == 15.0
        assert config.risk_percent == 2.5
        assert config.stop_loss_percent == 30.0
        assert config.high_confidence_threshold == 80
        
    def test_custom_config(self):
        config = VATConfig(
            min_gap_nifty=10.0,
            risk_percent=5.0,
            high_confidence_threshold=85
        )
        assert config.min_gap_nifty == 10.0
        assert config.risk_percent == 5.0
        assert config.high_confidence_threshold == 85


class TestGapScoring:
    """Test gap score calculation."""
    
    @pytest.fixture
    def strategy(self):
        return EnhancedVATStrategy()
    
    def test_gap_below_threshold_returns_zero(self, strategy):
        score = strategy.calculate_gap_score(gap=5.0, min_gap=7.0, avg_premium=100.0)
        assert score == 0.0
    
    def test_gap_at_threshold(self, strategy):
        score = strategy.calculate_gap_score(gap=7.0, min_gap=7.0, avg_premium=100.0)
        assert score > 0
        assert score < 50  # Should be moderate
    
    def test_high_gap_high_score(self, strategy):
        score = strategy.calculate_gap_score(gap=30.0, min_gap=7.0, avg_premium=100.0)
        assert score > 70  # High gap should give high score
    
    def test_gap_percentage_impacts_score(self, strategy):
        # Same gap, different avg premium
        score_low_pct = strategy.calculate_gap_score(gap=10.0, min_gap=7.0, avg_premium=200.0)
        score_high_pct = strategy.calculate_gap_score(gap=10.0, min_gap=7.0, avg_premium=50.0)
        assert score_high_pct > score_low_pct


class TestTimeScoring:
    """Test time-based scoring."""
    
    @pytest.fixture
    def strategy(self):
        return EnhancedVATStrategy()
    
    def test_expiry_day_highest_score(self, strategy):
        score = strategy.calculate_time_score(ExpiryPhase.EX_D0, is_optimal_window=True)
        assert score == 100  # Max score on expiry day during optimal window
    
    def test_ex_d1_score(self, strategy):
        score = strategy.calculate_time_score(ExpiryPhase.EX_D1, is_optimal_window=True)
        assert score == 100  # 80 + 20 bonus
    
    def test_regular_day_low_score(self, strategy):
        score = strategy.calculate_time_score(ExpiryPhase.REGULAR, is_optimal_window=False)
        assert score == 20  # Lowest score
    
    def test_optimal_window_bonus(self, strategy):
        score_optimal = strategy.calculate_time_score(ExpiryPhase.EX_D2, is_optimal_window=True)
        score_not_optimal = strategy.calculate_time_score(ExpiryPhase.EX_D2, is_optimal_window=False)
        assert score_optimal == score_not_optimal + 20


class TestConfidenceScoring:
    """Test overall confidence score calculation."""
    
    @pytest.fixture
    def strategy(self):
        return EnhancedVATStrategy()
    
    def test_all_high_scores_gives_high_confidence(self, strategy):
        confidence, strength = strategy.calculate_confidence_score(
            gap_score=100,
            momentum_score=100,
            time_score=100,
            greeks_score=100,
            max_pain_score=100
        )
        assert confidence == 100
        assert strength == "high"
    
    def test_all_low_scores_gives_skip(self, strategy):
        confidence, strength = strategy.calculate_confidence_score(
            gap_score=0,
            momentum_score=0,
            time_score=0,
            greeks_score=0,
            max_pain_score=0
        )
        assert confidence == 0
        assert strength == "skip"
    
    def test_medium_scores_gives_medium(self, strategy):
        confidence, strength = strategy.calculate_confidence_score(
            gap_score=70,
            momentum_score=65,
            time_score=60,
            greeks_score=70,
            max_pain_score=60
        )
        # Weighted: 70*0.3 + 65*0.25 + 60*0.2 + 70*0.15 + 60*0.1 = 21+16.25+12+10.5+6 = 65.75
        assert 60 <= confidence <= 80
        assert strength == "medium"
    
    def test_boundary_thresholds(self, strategy):
        # Test exactly at threshold
        _, strength_79 = strategy.calculate_confidence_score(79, 79, 79, 79, 79)
        _, strength_80 = strategy.calculate_confidence_score(80, 80, 80, 80, 80)
        assert strength_79 == "medium"
        assert strength_80 == "high"


class TestTradeParameters:
    """Test trade parameter calculations."""
    
    @pytest.fixture
    def strategy(self):
        return EnhancedVATStrategy()
    
    def test_stop_loss_calculation(self, strategy):
        sl, t1, t2, rr, profit = strategy.calculate_trade_parameters(
            entry_price=50.0,
            target_premium=100.0
        )
        # SL should be 30% below entry
        assert sl == 35.0  # 50 * 0.7 = 35
    
    def test_target_calculations(self, strategy):
        sl, t1, t2, rr, profit = strategy.calculate_trade_parameters(
            entry_price=50.0,
            target_premium=100.0
        )
        # Target 1: midway to fair value = 75
        assert t1 >= 75.0
        # Target 2: full fair value = 100
        assert t2 == 100.0
    
    def test_risk_reward_ratio(self, strategy):
        sl, t1, t2, rr, profit = strategy.calculate_trade_parameters(
            entry_price=50.0,
            target_premium=100.0
        )
        # Risk: 50 - 35 = 15
        # Reward: 75 - 50 = 25
        # RR: 25/15 = 1.67
        assert rr >= 1.5
    
    def test_minimum_stop_loss(self, strategy):
        """SL should not go below 50% of entry."""
        sl, _, _, _, _ = strategy.calculate_trade_parameters(
            entry_price=10.0,
            target_premium=50.0
        )
        assert sl >= 5.0  # Minimum 50% of entry


class TestExpiryPhaseDetection:
    """Test expiry phase detection logic."""
    
    @pytest.fixture
    def strategy(self):
        return EnhancedVATStrategy()
    
    @patch('app.services.strategies.vat.datetime')
    def test_thursday_nifty_is_ex_d0(self, mock_datetime, strategy):
        # Thursday is Nifty expiry
        mock_datetime.now.return_value = datetime(2026, 2, 5)  # A Thursday
        phase, days = strategy.detect_expiry_phase("NSE:NIFTY50-INDEX")
        assert phase == ExpiryPhase.EX_D0
        assert days == 0
    
    @patch('app.services.strategies.vat.datetime')
    def test_wednesday_nifty_is_ex_d1(self, mock_datetime, strategy):
        # Wednesday is 1 day before Nifty expiry
        mock_datetime.now.return_value = datetime(2026, 2, 4)  # A Wednesday
        phase, days = strategy.detect_expiry_phase("NSE:NIFTY50-INDEX")
        assert phase == ExpiryPhase.EX_D1
        assert days == 1
    
    @patch('app.services.strategies.vat.datetime')
    def test_wednesday_banknifty_is_ex_d0(self, mock_datetime, strategy):
        # Wednesday is BankNifty expiry
        mock_datetime.now.return_value = datetime(2026, 2, 4)  # A Wednesday
        phase, days = strategy.detect_expiry_phase("NSE:NIFTYBANK-INDEX")
        assert phase == ExpiryPhase.EX_D0
        assert days == 0


class TestGreeksScoring:
    """Test Greeks quality scoring."""
    
    @pytest.fixture
    def strategy(self):
        return EnhancedVATStrategy()
    
    def test_optimal_delta_gives_bonus(self, strategy):
        # Delta 0.4 is optimal
        score_optimal = strategy.calculate_greeks_score(delta=0.4, gamma=0.01, iv=20)
        score_poor = strategy.calculate_greeks_score(delta=0.1, gamma=0.01, iv=20)
        assert score_optimal > score_poor
    
    def test_high_gamma_gives_bonus(self, strategy):
        score_high_gamma = strategy.calculate_greeks_score(delta=0.4, gamma=0.03, iv=20)
        score_low_gamma = strategy.calculate_greeks_score(delta=0.4, gamma=0.005, iv=20)
        assert score_high_gamma > score_low_gamma
    
    def test_moderate_iv_gives_bonus(self, strategy):
        score_good_iv = strategy.calculate_greeks_score(delta=0.4, gamma=0.01, iv=20)
        score_extreme_iv = strategy.calculate_greeks_score(delta=0.4, gamma=0.01, iv=50)
        assert score_good_iv > score_extreme_iv


class TestSymbolConfig:
    """Test symbol-specific configuration."""
    
    @pytest.fixture
    def strategy(self):
        return EnhancedVATStrategy()
    
    def test_nifty_config(self, strategy):
        scan_range, strike_step, min_gap = strategy._get_symbol_config("NSE:NIFTY50-INDEX")
        assert scan_range == 500
        assert strike_step == 50
        assert min_gap == 7.0
    
    def test_banknifty_config(self, strategy):
        scan_range, strike_step, min_gap = strategy._get_symbol_config("NSE:NIFTYBANK-INDEX")
        assert scan_range == 1000
        assert strike_step == 100
        assert min_gap == 15.0


class TestOptimalTimeWindow:
    """Test optimal time window detection."""
    
    @pytest.fixture
    def strategy(self):
        return EnhancedVATStrategy()
    
    @patch('app.services.strategies.vat.datetime')
    def test_10am_is_optimal(self, mock_datetime, strategy):
        mock_datetime.now.return_value = datetime(2026, 2, 6, 10, 30)
        assert strategy.is_optimal_time_window() == True
    
    @patch('app.services.strategies.vat.datetime')
    def test_3pm_is_optimal(self, mock_datetime, strategy):
        mock_datetime.now.return_value = datetime(2026, 2, 6, 14, 45)
        assert strategy.is_optimal_time_window() == True
    
    @patch('app.services.strategies.vat.datetime')
    def test_9am_is_not_optimal(self, mock_datetime, strategy):
        mock_datetime.now.return_value = datetime(2026, 2, 6, 9, 30)
        assert strategy.is_optimal_time_window() == False
    
    @patch('app.services.strategies.vat.datetime')
    def test_4pm_is_not_optimal(self, mock_datetime, strategy):
        mock_datetime.now.return_value = datetime(2026, 2, 6, 16, 0)
        assert strategy.is_optimal_time_window() == False


# Integration test with mocked market data
class TestVATAnalysisIntegration:
    """Integration tests with mocked market service."""
    
    @pytest.fixture
    def mock_market_service(self):
        mock = MagicMock()
        mock.get_option_chain.return_value = {
            "success": True,
            "spot_price": 25000,
            "chain": [
                {
                    "strike_price": 25050,
                    "call": {"ltp": 100, "iv": 20, "greeks": {"delta": 0.45, "gamma": 0.01, "theta": -5}},
                    "put": {"ltp": 50, "iv": 18, "greeks": {"delta": -0.45, "gamma": 0.01, "theta": -4}}
                },
                {
                    "strike_price": 24950,
                    "call": {"ltp": 120, "iv": 22, "greeks": {"delta": 0.55, "gamma": 0.01, "theta": -6}},
                    "put": {"ltp": 80, "iv": 19, "greeks": {"delta": -0.55, "gamma": 0.01, "theta": -5}}
                }
            ]
        }
        mock.get_spot_price.return_value = {"success": True, "ltp": 25000}
        mock.get_quotes.return_value = {"success": True, "data": [{"ltp": 15}]}
        mock.get_historical_data.return_value = {"success": True, "data": []}
        return mock
    
    @pytest.mark.asyncio
    async def test_analyze_vat_returns_success(self, mock_market_service):
        with patch('app.services.strategies.vat.get_market_service', return_value=mock_market_service):
            strategy = EnhancedVATStrategy()
            result = await strategy.analyze_vat("NSE:NIFTY50-INDEX")
            
            assert result["success"] == True
            assert "spot_price" in result
            assert "opportunities" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
