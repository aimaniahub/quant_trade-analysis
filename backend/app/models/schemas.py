from pydantic import BaseModel, Field
from typing import Optional, Literal, List
from datetime import datetime
from enum import Enum


class MarketState(str, Enum):
    """Market state enumeration."""
    TREND = "TREND"
    RANGE = "RANGE"
    ADJUSTMENT = "ADJUSTMENT"
    NO_TRADE = "NO_TRADE"


class AdjustmentType(str, Enum):
    """Adjustment trade types."""
    A1 = "A1"  # Premium correction (tradable)
    A2 = "A2"  # Institutional hedge unwind (tradable)
    A3 = "A3"  # Fake breakout (not tradable)
    A4 = "A4"  # Liquidity distortion (not tradable)


class OptionType(str, Enum):
    """Option type enumeration."""
    CE = "CE"  # Call
    PE = "PE"  # Put


class OptionData(BaseModel):
    """Option data model."""
    symbol: str
    strike: float
    option_type: OptionType
    expiry: str
    ltp: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    oi: Optional[int] = None
    iv: Optional[float] = None


class Greeks(BaseModel):
    """Option Greeks model."""
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None


class OptionChainEntry(BaseModel):
    """Single entry in option chain."""
    strike: float
    call: Optional[OptionData] = None
    put: Optional[OptionData] = None
    call_greeks: Optional[Greeks] = None
    put_greeks: Optional[Greeks] = None


class MarketStateResponse(BaseModel):
    """Market state response model."""
    state: MarketState
    confidence: float = Field(ge=0, le=1)
    factors: List[str] = []
    timestamp: datetime = Field(default_factory=datetime.now)


class AdjustmentAlert(BaseModel):
    """Adjustment trade alert model."""
    type: AdjustmentType
    symbol: str
    strike: float
    option_type: OptionType
    reason: str
    confidence: Literal["LOW", "MEDIUM", "HIGH"]
    time_window: str
    invalidation: str
    is_tradable: bool


class TradeQualification(BaseModel):
    """Trade qualification check result."""
    is_qualified: bool
    checks: dict = Field(default_factory=dict)
    failed_reasons: List[str] = []
    recommendation: Literal["TRADE", "NO_TRADE", "WAIT"]
