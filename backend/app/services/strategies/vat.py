"""
Value Adjustment Theory (VAT) Strategy - Enhanced Version
----------------------------------------------------------
Implements the "Value Adjustment Theory" from the Trade Like Berlin Manuscript.

Core Principle: When equidistant strikes from spot have significantly different
premiums, the cheaper one is "undervalued" and will likely revert toward fair value.

Key Enhancements:
- Multi-parameter confidence scoring (0-100)
- Momentum analysis (spot velocity)
- Expiry timing logic (ex-d2, ex-d1, ex-d0 detection)
- Dynamic thresholds based on volatility
- Trade parameters (SL, targets, position sizing)
- Greeks quality assessment
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
from app.services.fyers_market import get_market_service


class ExpiryPhase(Enum):
    """Expiry day phases - VAT works best on ex-d2 to ex-d0."""
    REGULAR = "regular"      # More than 2 days to expiry
    EX_D2 = "ex-d2"          # 2 days before expiry
    EX_D1 = "ex-d1"          # 1 day before expiry  
    EX_D0 = "ex-d0"          # Expiry day


class SignalStrength(Enum):
    """Signal confidence levels."""
    HIGH = "high"            # 80-100: Strong trade opportunity
    MEDIUM = "medium"        # 60-79: Consider trading
    LOW = "low"              # 40-59: Paper trade only
    SKIP = "skip"            # <40: No trade


@dataclass
class VATConfig:
    """Configuration for VAT strategy."""
    # Gap thresholds (in INR)
    min_gap_nifty: float = 7.0
    min_gap_banknifty: float = 15.0
    
    # Scan parameters
    scan_range_nifty: int = 500       # Points from ATM
    scan_range_banknifty: int = 1000
    strike_step_nifty: int = 50
    strike_step_banknifty: int = 100
    
    # Risk management
    risk_percent: float = 2.5         # % of capital to risk per trade
    stop_loss_percent: float = 30.0   # SL as % of entry premium
    target_1_percent: float = 50.0    # First target (book 50%)
    target_2_percent: float = 100.0   # Second target (book remaining)
    min_risk_reward: float = 1.5      # Minimum RR ratio to trade
    
    # Scoring weights
    weight_gap: float = 0.30
    weight_momentum: float = 0.25
    weight_time: float = 0.20
    weight_greeks: float = 0.15
    weight_max_pain: float = 0.10
    
    # Time windows (in IST hours)
    optimal_start_hour: int = 10
    optimal_end_hour: int = 15
    
    # Confidence thresholds
    high_confidence_threshold: int = 80
    medium_confidence_threshold: int = 60
    low_confidence_threshold: int = 40


@dataclass
class VATSignal:
    """Enhanced VAT signal with full trade parameters."""
    # Basic identification
    signal_type: str                  # BUY_CE, BUY_PE, NONE
    undervalued_strike: int
    option_type: str                  # CE or PE
    
    # Pricing
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    
    # Gap analysis
    call_strike: int
    put_strike: int
    ce_premium: float
    pe_premium: float
    gap_amount: float
    gap_percentage: float
    
    # Scoring components (0-100 each)
    gap_score: float = 0.0
    momentum_score: float = 0.0       # -100 (bearish) to +100 (bullish), normalized to 0-100
    time_score: float = 0.0
    greeks_score: float = 0.0
    max_pain_score: float = 0.0
    
    # Final scores
    confidence_score: int = 0         # 0-100
    signal_strength: str = "skip"     # high, medium, low, skip
    
    # Risk metrics
    risk_reward_ratio: float = 0.0
    potential_profit: float = 0.0
    max_loss: float = 0.0
    
    # Greeks (if available)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    iv: float = 0.0
    
    # Context
    offset: int = 0                   # Distance from ATM
    is_tradeable: bool = False


@dataclass 
class MarketContext:
    """Current market context for VAT trading decision."""
    spot_price: float
    anchor_strike: int
    expiry_phase: str
    days_to_expiry: int
    current_time: str
    is_optimal_window: bool
    
    # Momentum
    spot_change_percent: float = 0.0
    spot_momentum_direction: str = "neutral"  # bullish, bearish, neutral
    
    # Volatility
    vix: float = 0.0
    iv_percentile: float = 0.0
    
    # Max pain
    max_pain_strike: int = 0
    distance_from_max_pain: int = 0


class EnhancedVATStrategy:
    """
    Enhanced Value Adjustment Theory strategy with multi-parameter analysis.
    
    Based on Trade Like Berlin manuscript:
    - Compare equidistant strike premiums
    - Buy undervalued option when gap is significant
    - Best on ex-d2 to ex-d0, especially 10AM-3PM
    - Combine with momentum for timing
    """
    
    def __init__(self, config: Optional[VATConfig] = None):
        self.market_service = get_market_service()
        self.config = config or VATConfig()
        
        # Symbol mappings
        self.NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"
        self.BANKNIFTY_SYMBOL = "NSE:NIFTYBANK-INDEX"
        
        # Cache for historical data
        self._spot_history: List[Tuple[datetime, float]] = []
        self._last_spot_fetch: Optional[datetime] = None
    
    def _get_symbol_config(self, symbol: str) -> Tuple[int, int, float]:
        """Get scan range, strike step, and min gap for symbol."""
        if "BANK" in symbol.upper():
            return (
                self.config.scan_range_banknifty,
                self.config.strike_step_banknifty,
                self.config.min_gap_banknifty
            )
        else:
            return (
                self.config.scan_range_nifty,
                self.config.strike_step_nifty,
                self.config.min_gap_nifty
            )
    
    def detect_expiry_phase(self, symbol: str) -> Tuple[ExpiryPhase, int]:
        """
        Detect current expiry phase and days to expiry.
        
        Returns:
            Tuple of (ExpiryPhase enum, days_to_expiry)
        """
        now = datetime.now()
        weekday = now.weekday()
        
        # Nifty expires Thursday, BankNifty expires Wednesday
        if "BANK" in symbol.upper():
            expiry_weekday = 2  # Wednesday
        else:
            expiry_weekday = 3  # Thursday
        
        # Calculate days to next expiry
        days_until_expiry = (expiry_weekday - weekday) % 7
        if days_until_expiry == 0:
            # Today is expiry day
            return (ExpiryPhase.EX_D0, 0)
        elif days_until_expiry == 1:
            return (ExpiryPhase.EX_D1, 1)
        elif days_until_expiry == 2:
            return (ExpiryPhase.EX_D2, 2)
        else:
            return (ExpiryPhase.REGULAR, days_until_expiry)
    
    def is_optimal_time_window(self) -> bool:
        """Check if current time is in optimal VAT trading window (10AM-3PM IST)."""
        now = datetime.now()
        return self.config.optimal_start_hour <= now.hour < self.config.optimal_end_hour
    
    def calculate_momentum_score(self, spot_price: float, symbol: str) -> Tuple[float, str]:
        """
        Calculate momentum score based on spot movement.
        
        Returns:
            Tuple of (score 0-100, direction string)
        """
        try:
            # Get recent historical data (5-minute candles for last hour)
            hist_data = self.market_service.get_historical_data(
                symbol=symbol,
                resolution="5",
                days=1
            )
            
            if not hist_data.get("success") or not hist_data.get("data"):
                return (50.0, "neutral")  # Neutral if no data
            
            candles = hist_data["data"]
            if len(candles) < 6:
                return (50.0, "neutral")
            
            # Get last 6 candles (30 minutes)
            recent_candles = candles[-6:]
            
            # Calculate price change
            start_price = recent_candles[0].get("close", spot_price)
            price_change_pct = ((spot_price - start_price) / start_price) * 100
            
            # Determine direction
            if price_change_pct > 0.3:
                direction = "bullish"
            elif price_change_pct < -0.3:
                direction = "bearish"
            else:
                direction = "neutral"
            
            # Convert to 0-100 score
            # Strong bearish (-1%+) = 0, Neutral = 50, Strong bullish (+1%+) = 100
            momentum_raw = (price_change_pct + 1) * 50  # Map -1 to +1 => 0 to 100
            momentum_score = max(0, min(100, momentum_raw))
            
            return (momentum_score, direction)
            
        except Exception:
            return (50.0, "neutral")
    
    def calculate_gap_score(self, gap: float, min_gap: float, avg_premium: float) -> float:
        """
        Calculate gap score (0-100) based on gap significance.
        
        Higher gap relative to threshold and premium = higher score.
        """
        if gap < min_gap:
            return 0.0
        
        # Gap ratio above threshold
        gap_ratio = gap / min_gap
        
        # Gap as percentage of average premium
        gap_pct = (gap / avg_premium * 100) if avg_premium > 0 else 0
        
        # Score: 50 points from ratio, 50 from percentage
        ratio_score = min(50, gap_ratio * 15)  # 3x threshold = 45 points
        pct_score = min(50, gap_pct * 2)       # 25% gap = 50 points
        
        return min(100, ratio_score + pct_score)
    
    def calculate_time_score(self, expiry_phase: ExpiryPhase, is_optimal_window: bool) -> float:
        """
        Calculate time score based on expiry proximity and time of day.
        
        VAT works best on ex-d2 to ex-d0, during 10AM-3PM.
        """
        # Base score by expiry phase
        phase_scores = {
            ExpiryPhase.EX_D0: 100,   # Best: Expiry day
            ExpiryPhase.EX_D1: 80,    # Very good: Day before
            ExpiryPhase.EX_D2: 60,    # Good: 2 days before
            ExpiryPhase.REGULAR: 20   # Poor: More than 2 days
        }
        base_score = phase_scores.get(expiry_phase, 20)
        
        # Bonus for optimal time window
        if is_optimal_window:
            time_bonus = 20
        else:
            time_bonus = 0
        
        return min(100, base_score + time_bonus)
    
    def calculate_greeks_score(self, delta: float, gamma: float, iv: float) -> float:
        """
        Calculate Greeks quality score.
        
        Prefer options with:
        - Higher delta (more responsive)
        - Higher gamma (on expiry day)
        - Moderate IV
        """
        score = 50.0  # Base score
        
        # Handle None values with defaults
        delta = delta if delta is not None else 0.4
        gamma = gamma if gamma is not None else 0.01
        iv = iv if iv is not None else 20
        
        # Delta bonus: prefer 0.3-0.5 delta (slightly OTM to ATM)
        if 0.25 <= abs(delta) <= 0.55:
            score += 25
        elif 0.15 <= abs(delta) <= 0.65:
            score += 15
        
        # Gamma bonus on expiry (high gamma = explosive moves)
        if gamma > 0.02:
            score += 15
        elif gamma > 0.01:
            score += 10
        
        # IV consideration: too high = expensive, too low = no movement
        if 15 <= iv <= 30:
            score += 10
        
        return min(100, score)
    
    def calculate_trade_parameters(
        self, 
        entry_price: float,
        target_premium: float
    ) -> Tuple[float, float, float, float, float]:
        """
        Calculate trade parameters: SL, targets, RR ratio.
        
        Returns:
            (stop_loss, target_1, target_2, risk_reward_ratio, potential_profit_pct)
        """
        # Stop loss
        sl = entry_price * (1 - self.config.stop_loss_percent / 100)
        sl = max(sl, entry_price * 0.5)  # Minimum 50% of entry
        
        # Targets based on theoretical fair value
        # Target 1: 50% of the way to fair value
        target_1 = entry_price + (target_premium - entry_price) * 0.5
        target_1 = max(target_1, entry_price * (1 + self.config.target_1_percent / 100))
        
        # Target 2: Full fair value
        target_2 = target_premium
        target_2 = max(target_2, entry_price * (1 + self.config.target_2_percent / 100))
        
        # Risk-reward calculation
        risk = entry_price - sl
        reward = target_1 - entry_price  # Use target 1 for RR
        rr_ratio = reward / risk if risk > 0 else 0
        
        # Potential profit percentage (to target 1)
        profit_pct = ((target_1 - entry_price) / entry_price) * 100
        
        return (round(sl, 2), round(target_1, 2), round(target_2, 2), 
                round(rr_ratio, 2), round(profit_pct, 1))
    
    def calculate_confidence_score(
        self,
        gap_score: float,
        momentum_score: float,
        time_score: float,
        greeks_score: float,
        max_pain_score: float = 50.0
    ) -> Tuple[int, str]:
        """
        Calculate final confidence score (0-100) and signal strength.
        
        Returns:
            Tuple of (confidence_score, signal_strength)
        """
        # Weighted sum
        confidence = (
            gap_score * self.config.weight_gap +
            momentum_score * self.config.weight_momentum +
            time_score * self.config.weight_time +
            greeks_score * self.config.weight_greeks +
            max_pain_score * self.config.weight_max_pain
        )
        
        confidence = int(round(confidence))
        
        # Determine strength
        if confidence >= self.config.high_confidence_threshold:
            strength = SignalStrength.HIGH.value
        elif confidence >= self.config.medium_confidence_threshold:
            strength = SignalStrength.MEDIUM.value
        elif confidence >= self.config.low_confidence_threshold:
            strength = SignalStrength.LOW.value
        else:
            strength = SignalStrength.SKIP.value
        
        return (confidence, strength)
    
    async def get_market_context(self, symbol: str) -> MarketContext:
        """Get current market context for VAT trading decision."""
        # Get spot price
        spot_data = self.market_service.get_spot_price(symbol)
        spot_price = spot_data.get("ltp", 0) if spot_data.get("success") else 0
        
        # Get symbol config
        _, strike_step, _ = self._get_symbol_config(symbol)
        anchor_strike = round(spot_price / strike_step) * strike_step
        
        # Detect expiry phase
        expiry_phase, days_to_expiry = self.detect_expiry_phase(symbol)
        
        # Check optimal window
        is_optimal = self.is_optimal_time_window()
        
        # Calculate momentum
        momentum_score, momentum_dir = self.calculate_momentum_score(spot_price, symbol)
        
        # Get VIX if available
        vix = 0.0
        try:
            vix_data = self.market_service.get_quotes(["NSE:INDIAVIX-INDEX"])
            if vix_data.get("success") and vix_data.get("data"):
                vix = vix_data["data"][0].get("ltp", 0)
        except Exception:
            pass
        
        return MarketContext(
            spot_price=spot_price,
            anchor_strike=anchor_strike,
            expiry_phase=expiry_phase.value,
            days_to_expiry=days_to_expiry,
            current_time=datetime.now().strftime("%H:%M:%S"),
            is_optimal_window=is_optimal,
            spot_change_percent=0,
            spot_momentum_direction=momentum_dir,
            vix=vix,
            iv_percentile=0,
            max_pain_strike=0,
            distance_from_max_pain=0
        )
    
    async def analyze_vat_advanced(
        self,
        symbol: str = "NSE:NIFTY50-INDEX",
        min_confidence: int = 0,
        include_greeks: bool = True,
        max_signals: int = 10
    ) -> Dict[str, Any]:
        """
        Advanced VAT analysis with confidence scoring and trade parameters.
        
        Args:
            symbol: Index symbol
            min_confidence: Minimum confidence score to include (0-100)
            include_greeks: Whether to include Greeks in analysis
            max_signals: Maximum signals to return
            
        Returns:
            Dict with market context, signals by confidence level, and full analysis
        """
        # Get option chain
        scan_range, strike_step, min_gap = self._get_symbol_config(symbol)
        strike_count = (scan_range // strike_step) * 2 + 10
        
        chain_result = self.market_service.get_option_chain(
            symbol=symbol, 
            strike_count=strike_count
        )
        
        if not chain_result.get("success"):
            return {
                "success": False,
                "error": chain_result.get("error", "Failed to fetch option chain")
            }
        
        spot_price = chain_result.get("spot_price", 0)
        chain_data = chain_result.get("chain", [])
        
        if not spot_price or not chain_data:
            return {"success": False, "error": "No market data available"}
        
        # Build chain map
        chain_map = {item["strike_price"]: item for item in chain_data}
        
        # Get market context
        context = await self.get_market_context(symbol)
        
        # Calculate momentum
        momentum_score, momentum_dir = self.calculate_momentum_score(spot_price, symbol)
        context.spot_momentum_direction = momentum_dir
        
        # Detect expiry phase
        expiry_phase, days_to_expiry = self.detect_expiry_phase(symbol)
        
        # Calculate time score
        time_score = self.calculate_time_score(expiry_phase, context.is_optimal_window)
        
        # Anchor strike
        anchor_strike = round(spot_price / strike_step) * strike_step
        
        # Analyze equidistant pairs
        all_signals: List[VATSignal] = []
        
        for offset in range(strike_step, scan_range + strike_step, strike_step):
            call_strike = anchor_strike + offset
            put_strike = anchor_strike - offset
            
            call_data = chain_map.get(call_strike, {}).get("call")
            put_data = chain_map.get(put_strike, {}).get("put")
            
            if not call_data or not put_data:
                continue
            
            ce_ltp = call_data.get("ltp", 0)
            pe_ltp = put_data.get("ltp", 0)
            
            if ce_ltp <= 0 or pe_ltp <= 0:
                continue
            
            # Calculate gap
            gap = abs(ce_ltp - pe_ltp)
            avg_premium = (ce_ltp + pe_ltp) / 2
            gap_pct = (gap / avg_premium * 100) if avg_premium > 0 else 0
            
            # Calculate gap score
            gap_score = self.calculate_gap_score(gap, min_gap, avg_premium)
            
            # Determine undervalued leg
            if ce_ltp < pe_ltp:
                signal_type = "BUY_CE"
                undervalued_strike = call_strike
                entry_price = ce_ltp
                target_premium = pe_ltp
                option_type = "CE"
                greeks = call_data.get("greeks") or {}
                delta = greeks.get("delta") if greeks.get("delta") is not None else 0.4
                gamma = greeks.get("gamma") if greeks.get("gamma") is not None else 0.01
                theta = greeks.get("theta") if greeks.get("theta") is not None else 0
                iv = call_data.get("iv") if call_data.get("iv") is not None else 20
            else:
                signal_type = "BUY_PE"
                undervalued_strike = put_strike
                entry_price = pe_ltp
                target_premium = ce_ltp
                option_type = "PE"
                greeks = put_data.get("greeks") or {}
                delta = greeks.get("delta") if greeks.get("delta") is not None else -0.4
                gamma = greeks.get("gamma") if greeks.get("gamma") is not None else 0.01
                theta = greeks.get("theta") if greeks.get("theta") is not None else 0
                iv = put_data.get("iv") if put_data.get("iv") is not None else 20
            
            # Skip if gap too small
            if gap < min_gap:
                signal_type = "NONE"
            
            # Calculate Greeks score
            greeks_score = self.calculate_greeks_score(delta, gamma, iv)
            
            # Momentum alignment bonus
            # For CE: bullish momentum is good. For PE: bearish is good.
            if signal_type == "BUY_CE" and momentum_dir == "bullish":
                aligned_momentum = momentum_score
            elif signal_type == "BUY_PE" and momentum_dir == "bearish":
                aligned_momentum = 100 - momentum_score  # Invert for PE
            else:
                aligned_momentum = 50  # Neutral
            
            # Calculate confidence
            confidence, strength = self.calculate_confidence_score(
                gap_score=gap_score,
                momentum_score=aligned_momentum,
                time_score=time_score,
                greeks_score=greeks_score,
                max_pain_score=50  # Default for now
            )
            
            # Calculate trade parameters
            sl, target_1, target_2, rr_ratio, profit_pct = self.calculate_trade_parameters(
                entry_price, target_premium
            )
            
            # Determine if tradeable
            is_tradeable = (
                signal_type != "NONE" and
                confidence >= min_confidence and
                rr_ratio >= self.config.min_risk_reward
            )
            
            signal = VATSignal(
                signal_type=signal_type,
                undervalued_strike=undervalued_strike,
                option_type=option_type,
                entry_price=entry_price,
                stop_loss=sl,
                target_1=target_1,
                target_2=target_2,
                call_strike=call_strike,
                put_strike=put_strike,
                ce_premium=ce_ltp,
                pe_premium=pe_ltp,
                gap_amount=round(gap, 2),
                gap_percentage=round(gap_pct, 1),
                gap_score=round(gap_score, 1),
                momentum_score=round(aligned_momentum, 1),
                time_score=round(time_score, 1),
                greeks_score=round(greeks_score, 1),
                max_pain_score=50,
                confidence_score=confidence,
                signal_strength=strength,
                risk_reward_ratio=rr_ratio,
                potential_profit=profit_pct,
                max_loss=round(self.config.stop_loss_percent, 1),
                delta=round(delta, 3) if include_greeks else 0,
                gamma=round(gamma, 4) if include_greeks else 0,
                theta=round(theta, 2) if include_greeks else 0,
                iv=round(iv, 1) if include_greeks else 0,
                offset=offset,
                is_tradeable=is_tradeable
            )
            
            all_signals.append(signal)
        
        # Filter and categorize signals
        tradeable_signals = [s for s in all_signals if s.is_tradeable]
        tradeable_signals.sort(key=lambda x: x.confidence_score, reverse=True)
        
        high_confidence = [s for s in tradeable_signals if s.signal_strength == "high"]
        medium_confidence = [s for s in tradeable_signals if s.signal_strength == "medium"]
        low_confidence = [s for s in tradeable_signals if s.signal_strength == "low"]
        
        # Convert signals to dicts for JSON serialization
        def signal_to_dict(s: VATSignal) -> Dict[str, Any]:
            return {
                "signal_type": s.signal_type,
                "undervalued_strike": s.undervalued_strike,
                "option_type": s.option_type,
                "entry_price": s.entry_price,
                "stop_loss": s.stop_loss,
                "target_1": s.target_1,
                "target_2": s.target_2,
                "call_strike": s.call_strike,
                "put_strike": s.put_strike,
                "ce_premium": s.ce_premium,
                "pe_premium": s.pe_premium,
                "gap_amount": s.gap_amount,
                "gap_percentage": s.gap_percentage,
                "scoring": {
                    "gap_score": s.gap_score,
                    "momentum_score": s.momentum_score,
                    "time_score": s.time_score,
                    "greeks_score": s.greeks_score,
                    "max_pain_score": s.max_pain_score,
                    "confidence_score": s.confidence_score,
                    "signal_strength": s.signal_strength
                },
                "risk_management": {
                    "risk_reward_ratio": s.risk_reward_ratio,
                    "potential_profit_pct": s.potential_profit,
                    "max_loss_pct": s.max_loss
                },
                "greeks": {
                    "delta": s.delta,
                    "gamma": s.gamma,
                    "theta": s.theta,
                    "iv": s.iv
                } if include_greeks else None,
                "offset": s.offset,
                "is_tradeable": s.is_tradeable
            }
        
        return {
            "success": True,
            "symbol": symbol,
            "market_context": {
                "spot_price": context.spot_price,
                "anchor_strike": context.anchor_strike,
                "expiry_phase": context.expiry_phase,
                "days_to_expiry": context.days_to_expiry,
                "current_time": context.current_time,
                "is_optimal_window": context.is_optimal_window,
                "momentum_direction": context.spot_momentum_direction,
                "vix": context.vix
            },
            "summary": {
                "total_signals": len(tradeable_signals),
                "high_confidence": len(high_confidence),
                "medium_confidence": len(medium_confidence),
                "low_confidence": len(low_confidence),
                "best_signal": signal_to_dict(tradeable_signals[0]) if tradeable_signals else None
            },
            "signals": {
                "high": [signal_to_dict(s) for s in high_confidence[:max_signals]],
                "medium": [signal_to_dict(s) for s in medium_confidence[:max_signals]],
                "low": [signal_to_dict(s) for s in low_confidence[:max_signals]]
            },
            "all_pairs": [signal_to_dict(s) for s in all_signals]
        }
    
    async def analyze_vat(self, symbol: str = "NSE:NIFTY50-INDEX") -> Dict[str, Any]:
        """
        Legacy VAT analysis method - returns simplified format for backward compatibility.
        """
        result = await self.analyze_vat_advanced(symbol, min_confidence=0, include_greeks=False)
        
        if not result.get("success"):
            return result
        
        # Convert to legacy format
        opportunities = []
        for pair in result.get("all_pairs", []):
            if pair.get("gap_amount", 0) >= self.config.min_gap_nifty:
                opportunities.append({
                    "offset": pair["offset"],
                    "call_strike": pair["call_strike"],
                    "put_strike": pair["put_strike"],
                    "ce_ltp": pair["ce_premium"],
                    "pe_ltp": pair["pe_premium"],
                    "gap": pair["gap_amount"],
                    "is_opportunity": pair["gap_amount"] >= self.config.min_gap_nifty,
                    "signal": pair["signal_type"],
                    "undervalued_strike": pair["undervalued_strike"],
                    "entry_price": pair["entry_price"],
                    "theoretical_target": pair["target_2"],
                    # New fields (enhanced)
                    "confidence_score": pair["scoring"]["confidence_score"],
                    "signal_strength": pair["scoring"]["signal_strength"],
                    "stop_loss": pair["stop_loss"],
                    "target_1": pair["target_1"],
                    "risk_reward_ratio": pair["risk_management"]["risk_reward_ratio"]
                })
        
        opportunities.sort(key=lambda x: x.get("gap", 0), reverse=True)
        
        return {
            "success": True,
            "symbol": symbol,
            "spot_price": result["market_context"]["spot_price"],
            "anchor_strike": result["market_context"]["anchor_strike"],
            "expiry_phase": result["market_context"]["expiry_phase"],
            "is_optimal_window": result["market_context"]["is_optimal_window"],
            "total_opportunities": len([o for o in opportunities if o["is_opportunity"]]),
            "opportunities": [o for o in opportunities if o["is_opportunity"]],
            "full_analysis": opportunities
        }


# Singleton instance
_vat_strategy: Optional[EnhancedVATStrategy] = None


def get_vat_strategy() -> EnhancedVATStrategy:
    """Get the VAT strategy instance."""
    global _vat_strategy
    if _vat_strategy is None:
        _vat_strategy = EnhancedVATStrategy()
    return _vat_strategy
