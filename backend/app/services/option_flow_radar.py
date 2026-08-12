"""
Option Flow Radar Service v2
============================
Detects early institutional accumulation in options before the underlying
stock shows a significant price move.

v2 Changes:
- Full 180-stock NSE FNO watchlist
- ONE best strike per stock (not multiple duplicates)
- 3-day rolling average volume per option strike for baseline comparison
- Volume spike REQUIRED alongside OI spike (both must confirm)
- LIS v2: Volume spike gets 25% weight
- Full Greek analysis with interpretation (Delta bias, Gamma risk, Theta drain, Vega sensitivity)
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import math
import time
import logging

from app.services.fyers_market import get_market_service
from app.services.fyers_auth import get_auth_service
from app.services.fno_stocks import (
    FNO_STOCKS,
    FNO_INDICES,
    get_fno_universe,
    filter_valid_symbols,
    is_valid_symbol,
    mark_invalid_symbol,
)
from app.utils.market_hours import is_market_open

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Canonical NSE FNO watchlist (shared with MA / scanners)
# ─────────────────────────────────────────────────────────────────

ALL_FNO_STOCKS = filter_valid_symbols(list(FNO_STOCKS))
INDICES_WATCHLIST = filter_valid_symbols(list(FNO_INDICES))
ALL_FNO_WATCHLIST = filter_valid_symbols(get_fno_universe(include_indices=True))

# Human-readable name map (auto-builds from symbol, override specific ones)
_OVERRIDES = {
    "NSE:NIFTY50-INDEX": "NIFTY",
    "NSE:NIFTYBANK-INDEX": "BANKNIFTY",
    "NSE:FINNIFTY-INDEX": "FINNIFTY",
    "NSE:M&M-EQ": "M&M",
    "NSE:BAJAJ-AUTO-EQ": "BAJAJ-AUTO",
    "NSE:L&TFH-EQ": "L&TFH",
    "NSE:LT-EQ": "L&T",
}


def _sym_name(symbol: str) -> str:
    if symbol in _OVERRIDES:
        return _OVERRIDES[symbol]
    # NSE:SBIN-EQ → SBIN
    part = symbol.split(":")[-1]
    return part.replace("-EQ", "").replace("-INDEX", "")


# ─────────────────────────────────────────────────────────────────
# LIS v2 Calculation  (volume spike included)
# ─────────────────────────────────────────────────────────────────

def compute_lis_v2(
    oi_change_pct: float,           # % OI change from prev day
    vol_spike_ratio: float,         # current_vol / 3day_avg_vol  (1.0 = normal)
    option_price_change_pct: float, # % LTP change from prev close
    underlying_vwap_dev_pct: float, # % deviation of spot from 5-min VWAP
    delivery_ratio: float,          # delivery vol / 5-day avg (1.0 = normal)
    above_ema20: bool,              # underlying above 20-period EMA on 5-min
) -> float:
    """
    Leading Indicator Score v2 (0–100):
      OI change:        30%  (requires OI spike alongside volume)
      Volume spike:     25%  (NEW – must confirm OI signal)
      Option momentum:  15%
      VWAP deviation:   15%
      EMA trigger:      10%
      Delivery ratio:    5%
    """
    # 1. OI score – 20% OI change → full 30 pts
    oi_score = min(abs(oi_change_pct) / 20.0, 1.0) * 30.0

    # 2. Volume spike score – 5x average → full 25 pts
    #    vol_spike_ratio must be > 1 to contribute
    vol_excess = max(vol_spike_ratio - 1.0, 0.0)
    vol_score = min(vol_excess / 4.0, 1.0) * 25.0

    # 3. Option price momentum – only positive counts as bullish
    momentum_score = min(max(option_price_change_pct, 0.0) / 5.0, 1.0) * 15.0

    # 4. VWAP deviation – low deviation = stock coiling → good signal
    vwap_score = (1.0 - min(abs(underlying_vwap_dev_pct) / 2.0, 1.0)) * 15.0

    # 5. EMA trigger
    trigger = 10.0 if above_ema20 else 0.0

    # 6. Delivery ratio
    delivery_score = min(delivery_ratio / 2.0, 1.0) * 5.0

    total = oi_score + vol_score + momentum_score + vwap_score + trigger + delivery_score
    return round(min(total, 100.0), 1)


# ─────────────────────────────────────────────────────────────────
# Signal Classification (OI × Price × Underlying matrix)
# ─────────────────────────────────────────────────────────────────

def classify_signal(
    oi_change_pct: float,
    option_price_change_pct: float,
    underlying_price_change_pct: float,
) -> Dict[str, str]:
    """
    OI▲ + Price▲ + Underlying▲/flat  →  Fresh Long Call Buying  (Strong Bullish)
    OI▲ + Price▲ + Underlying▼       →  Bearish hedge / spec      (Weak Bullish)
    OI▲ + Price▼ + Underlying▼       →  Call Writing (Bearish)    (Bearish)
    OI▼ + Price▲ + Underlying▲       →  Long Unwinding            (Exhaustion)
    OI▲ + Volume spike only           →  Smart Money Accumulation  (Neutral/Watch)
    """
    oi_up = oi_change_pct > 5
    oi_dn = oi_change_pct < -5
    pr_up = option_price_change_pct > 2
    pr_dn = option_price_change_pct < -2
    ul_dn = underlying_price_change_pct < 0

    if oi_up and pr_up and not ul_dn:
        return {"signal": "STRONG_BULLISH", "label": "Fresh Long Buying", "icon": "🟢", "color": "emerald"}
    elif oi_up and pr_up and ul_dn:
        return {"signal": "WEAK_BULLISH", "label": "Bearish Hedge/Spec", "icon": "🟡", "color": "amber"}
    elif oi_up and pr_dn and ul_dn:
        return {"signal": "BEARISH", "label": "Call Writing", "icon": "🔴", "color": "rose"}
    elif oi_dn and pr_up:
        return {"signal": "EXHAUSTION", "label": "Long Unwinding", "icon": "🔴", "color": "rose"}
    elif oi_up:
        return {"signal": "ACCUMULATION", "label": "Smart Money Accum.", "icon": "🔵", "color": "blue"}
    else:
        return {"signal": "NEUTRAL", "label": "Neutral/Inconclusive", "icon": "⚪", "color": "zinc"}


def get_conviction(lis: float, signal_type: str, vol_spike_ratio: float) -> Dict[str, str]:
    """
    HIGH conviction: LIS ≥ 70 + STRONG_BULLISH + vol spike ≥ 2×
    MEDIUM: LIS 40–69 or vol spike 1.5–2×
    LOW: below thresholds
    """
    high_vol = vol_spike_ratio >= 2.0
    if lis >= 70 and signal_type in ("STRONG_BULLISH", "ACCUMULATION") and high_vol:
        return {"level": "HIGH", "icon": "🔴", "label": "High Conviction"}
    elif lis >= 40 or (lis >= 30 and high_vol):
        return {"level": "MEDIUM", "icon": "🟡", "label": "Medium"}
    else:
        return {"level": "LOW", "icon": "⚪", "label": "Low"}


# ─────────────────────────────────────────────────────────────────
# Greek Interpretation
# ─────────────────────────────────────────────────────────────────

def interpret_greeks(
    delta: Optional[float],
    gamma: Optional[float],
    theta: Optional[float],
    vega: Optional[float],
    opt_type: str,
) -> Dict[str, Any]:
    """
    Produces human-readable Greek interpretation for display.
    """
    d = delta or 0.0
    g = gamma or 0.0
    t = theta or 0.0
    v = vega or 0.0

    # Delta bias
    abs_d = abs(d)
    if abs_d >= 0.6:
        delta_bias = "DEEP_ITM"
        delta_label = "Deep ITM"
    elif abs_d >= 0.4:
        delta_bias = "ATM"
        delta_label = "Near ATM"
    elif abs_d >= 0.2:
        delta_bias = "OTM"
        delta_label = "OTM"
    else:
        delta_bias = "DEEP_OTM"
        delta_label = "Deep OTM"

    # Gamma risk
    if g >= 0.01:
        gamma_risk = "HIGH"
    elif g >= 0.003:
        gamma_risk = "MEDIUM"
    else:
        gamma_risk = "LOW"

    # Theta daily decay
    theta_daily = abs(t)
    if theta_daily >= 5:
        theta_label = f"-₹{theta_daily:.1f}/day"
        theta_risk = "HIGH"
    elif theta_daily >= 1:
        theta_label = f"-₹{theta_daily:.1f}/day"
        theta_risk = "MEDIUM"
    else:
        theta_label = f"-₹{theta_daily:.2f}/day"
        theta_risk = "LOW"

    # Vega sensitivity
    if v >= 10:
        vega_sens = "HIGH"
    elif v >= 3:
        vega_sens = "MEDIUM"
    else:
        vega_sens = "LOW"

    return {
        "delta_bias": delta_bias,
        "delta_label": delta_label,
        "delta_value": round(d, 4),
        "gamma_risk": gamma_risk,
        "gamma_value": round(g, 6),
        "theta_risk": theta_risk,
        "theta_label": theta_label,
        "theta_value": round(t, 2),
        "vega_sensitivity": vega_sens,
        "vega_value": round(v, 2),
    }


# ─────────────────────────────────────────────────────────────────
# Utility: EMA + VWAP (no pandas)
# ─────────────────────────────────────────────────────────────────

def compute_ema(prices: List[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    k = 2.0 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]:
        ema = p * k + ema * (1 - k)
    return ema


def compute_vwap(candles: List[Dict]) -> Optional[float]:
    total_vol = sum(c.get("volume", 0) for c in candles)
    if total_vol == 0:
        return None
    weighted = sum(
        ((c.get("high", 0) + c.get("low", 0) + c.get("close", 0)) / 3) * c.get("volume", 0)
        for c in candles
    )
    return weighted / total_vol


# ─────────────────────────────────────────────────────────────────
# Main Radar Service v2
# ─────────────────────────────────────────────────────────────────

class OptionFlowRadarService:
    """
    Option Flow Radar v2 – detects early institutional accumulation.
    - 180 FNO stocks
    - Best single strike per stock
    - 3-day volume baseline
    - Full Greek analysis
    """

    def __init__(self):
        self.market_service = get_market_service()
        self.auth_service = get_auth_service()
        # In-memory cache for 3-day vol averages  {option_symbol: (avg_vol, fetched_at)}
        self._vol_cache: Dict[str, Tuple[float, datetime]] = {}
        self._VOL_CACHE_TTL = 3600  # 1 hour
        # Last scan cache (used by confluence + UI without re-hitting Fyers)
        self._last_scan: Optional[Dict[str, Any]] = None
        self._last_scan_at: Optional[datetime] = None
        self._scan_running = False

    def _is_authenticated(self) -> bool:
        return bool(self.auth_service.get_fyers_model())

    def _persist_last_scan(self) -> None:
        """Optional Redis durability for last radar scan (confluence after restart)."""
        if not self._last_scan or not self._last_scan_at:
            return
        try:
            from app.services import redis_client as rc
            if not rc.is_available():
                return
            rc.set_json(
                rc.key("radar", "last_scan"),
                {
                    "scan": self._last_scan,
                    "at": self._last_scan_at.isoformat(),
                },
                ttl=1800,
            )
        except Exception:
            pass

    def _hydrate_last_scan_from_redis(self) -> None:
        if self._last_scan:
            return
        try:
            from app.services import redis_client as rc
            if not rc.is_available():
                return
            raw = rc.get_json(rc.key("radar", "last_scan"))
            if not raw or not isinstance(raw, dict):
                return
            scan = raw.get("scan")
            at = raw.get("at")
            if not scan:
                return
            self._last_scan = scan
            try:
                self._last_scan_at = datetime.fromisoformat(at) if at else datetime.now()
            except Exception:
                self._last_scan_at = datetime.now()
        except Exception:
            pass

    def get_cached_scan(self, max_age_seconds: int = 900) -> Optional[Dict[str, Any]]:
        """Return last scan if fresh enough (memory, then Redis)."""
        self._hydrate_last_scan_from_redis()
        if not self._last_scan or not self._last_scan_at:
            return None
        age = (datetime.now() - self._last_scan_at).total_seconds()
        if age > max_age_seconds:
            return None
        return {**self._last_scan, "cache_age_seconds": round(age, 1)}

    def get_last_scan(self) -> Optional[Dict[str, Any]]:
        self._hydrate_last_scan_from_redis()
        if not self._last_scan:
            return None
        age = (
            (datetime.now() - self._last_scan_at).total_seconds()
            if self._last_scan_at
            else None
        )
        return {**self._last_scan, "cache_age_seconds": age, "scan_running": self._scan_running}

    # ── Underlying spot + 5-min history ──────────────────────────

    def _get_underlying_data(self, symbol: str) -> Dict[str, Any]:
        spot_resp = self.market_service.get_spot_price(symbol)
        if not spot_resp.get("success"):
            return {}

        ltp = spot_resp.get("ltp") or 0
        chg_p = spot_resp.get("change_percent") or 0

        hist = self.market_service.get_historical_data(
            symbol=symbol, resolution="5", days=1,
        )
        candles = hist.get("candles", [])
        closes = [c["close"] for c in candles]
        vwap = compute_vwap(candles) or ltp
        ema20 = compute_ema(closes, 20) or ltp
        vwap_dev = ((ltp - vwap) / vwap * 100) if vwap else 0

        return {
            "ltp": ltp,
            "change_pct": chg_p,
            "vwap": vwap,
            "ema20": ema20,
            "vwap_dev_pct": round(vwap_dev, 3),
            "above_ema20": ltp > ema20,
            "candles_5min": candles[-60:],
        }

    # ── 3-day average volume for a specific option contract ──────

    def _get_3day_vol_avg(self, option_symbol: str) -> float:
        """
        Fetch 3 daily candles for a specific option contract and
        return the average volume. Uses in-memory cache (TTL 1h).
        Returns 0 if data unavailable.
        """
        now = datetime.now()
        cached = self._vol_cache.get(option_symbol)
        if cached:
            avg_vol, fetched_at = cached
            if (now - fetched_at).total_seconds() < self._VOL_CACHE_TTL:
                return avg_vol

        try:
            hist = self.market_service.get_historical_data(
                symbol=option_symbol,
                resolution="D",
                days=5,  # fetch 5 trading days, use last 3
            )
            candles = hist.get("candles", [])
            if len(candles) >= 2:
                # Use last 3 completed days (skip today)
                completed = candles[:-1] if len(candles) > 1 else candles
                recent_3 = completed[-3:] if len(completed) >= 3 else completed
                vols = [c.get("volume", 0) for c in recent_3 if c.get("volume", 0) > 0]
                avg_vol = sum(vols) / len(vols) if vols else 0.0
            else:
                avg_vol = 0.0

            self._vol_cache[option_symbol] = (avg_vol, now)
            return avg_vol

        except Exception as e:
            logger.debug(f"3-day vol avg failed for {option_symbol}: {e}")
            return 0.0

    # ── Process option chain → best single strike ─────────────────

    def _process_option_chain(
        self,
        symbol: str,
        underlying: Dict[str, Any],
        strike_count: int = 10,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch option chain for symbol, compute LIS v2, return the SINGLE
        best-scoring strike (highest LIS) that satisfies ALL of:
          1. OI change ≥ 5% (unusual OI activity)
          2. Volume ≥ minimum threshold (not zero)
          3. Volume spike ratio ≥ 1.2× 3-day average (confirmed unusual volume)

        Returns None if no qualifying strike found.
        """
        chain_resp = self.market_service.get_option_chain(symbol, strike_count)
        if not chain_resp.get("success"):
            return None

        chain = chain_resp.get("chain", [])
        spot = chain_resp.get("spot_price") or underlying.get("ltp", 0)
        expiries = chain_resp.get("expiries", [])

        # Normalize expiry to string
        if expiries:
            first_exp = expiries[0]
            nearest_expiry = (
                first_exp.get("expiry") or first_exp.get("date") or "N/A"
                if isinstance(first_exp, dict) else str(first_exp)
            )
        else:
            nearest_expiry = "N/A"

        ul_chg_pct = underlying.get("change_pct", 0)
        vwap_dev = underlying.get("vwap_dev_pct", 0)
        above_ema = underlying.get("above_ema20", False)
        sym_name = _sym_name(symbol)

        # ── Phase 1: Collect all candidate contracts with basic filters ──
        candidates = []

        for row in chain:
            strike = row.get("strike_price")
            if not strike or strike <= 0:
                continue

            atm_dist_pct = abs(strike - spot) / spot * 100 if spot else 999
            # Skip very deep OTM (> 20% away from spot) — unlikely institutional
            if atm_dist_pct > 20:
                continue

            for opt_type, key in [("CE", "call"), ("PE", "put")]:
                opt = row.get(key)
                if not opt:
                    continue

                oi_change_pct = opt.get("oi_change_pct") or 0
                ltp_chg_pct = opt.get("chg_pct") or 0
                oi = opt.get("oi") or 0
                volume = opt.get("volume") or 0
                ltp = opt.get("ltp") or 0
                iv = opt.get("iv") or 0

                # HARD FILTER 1: both OI and volume must be non-zero
                if oi == 0 or volume == 0:
                    continue

                # HARD FILTER 2: OI must show meaningful change
                if abs(oi_change_pct) < 5:
                    continue

                # HARD FILTER 3: Option must have traded (min 100 contracts)
                if volume < 100:
                    continue

                candidates.append({
                    "strike": strike,
                    "opt_type": opt_type,
                    "opt": opt,
                    "atm_dist_pct": atm_dist_pct,
                    "oi_change_pct": oi_change_pct,
                    "ltp_chg_pct": ltp_chg_pct,
                    "oi": oi,
                    "volume": volume,
                    "ltp": ltp,
                    "iv": iv,
                })

        if not candidates:
            return None

        # ── Phase 2: Sort by OI change × volume to prioritize best candidates ──
        # Score = abs(OI%) * log(volume+1) — quick pre-rank without API calls
        def prelim_score(c):
            return abs(c["oi_change_pct"]) * math.log(c["volume"] + 1)

        candidates.sort(key=prelim_score, reverse=True)
        # Evaluate at most top 5 to avoid too many API calls
        top_candidates = candidates[:5]

        # ── Phase 3: Fetch 3-day vol avg for top candidates & compute LIS v2 ──
        scored = []

        for cand in top_candidates:
            opt = cand["opt"]
            opt_sym = opt.get("symbol", "")
            vol_3day_avg = self._get_3day_vol_avg(opt_sym) if opt_sym else 0.0

            # Volume spike ratio
            vol_spike_ratio = (
                cand["volume"] / vol_3day_avg if vol_3day_avg > 0 else 1.0
            )

            # HARD FILTER 4: volume must be ≥ 1.2× the 3-day average
            # (If 3-day avg is 0, use current volume as reference — still include)
            if vol_3day_avg > 0 and vol_spike_ratio < 1.2:
                continue

            lis = compute_lis_v2(
                oi_change_pct=cand["oi_change_pct"],
                vol_spike_ratio=vol_spike_ratio,
                option_price_change_pct=cand["ltp_chg_pct"],
                underlying_vwap_dev_pct=vwap_dev,
                # Delivery ratio is not available intraday from Fyers OC;
                # keep neutral 1.0 so LIS delivery weight does not invent a spike.
                delivery_ratio=1.0,
                above_ema20=above_ema,
            )

            signal = classify_signal(cand["oi_change_pct"], cand["ltp_chg_pct"], ul_chg_pct)
            conviction = get_conviction(lis, signal["signal"], vol_spike_ratio)

            # Greeks from option data
            delta = opt.get("delta")
            gamma = opt.get("gamma")
            theta = opt.get("theta")
            vega = opt.get("vega")
            greek_interp = interpret_greeks(delta, gamma, theta, vega, cand["opt_type"])

            # Unusual flags
            unusual_flags = []
            if abs(cand["oi_change_pct"]) > 20:
                unusual_flags.append(f"OI spike {cand['oi_change_pct']:+.1f}%")
            if vol_spike_ratio >= 3:
                unusual_flags.append(f"Vol {vol_spike_ratio:.1f}× avg")
            elif vol_spike_ratio >= 2:
                unusual_flags.append(f"Vol {vol_spike_ratio:.1f}× avg")
            if cand["iv"] and cand["iv"] > 40:
                unusual_flags.append(f"High IV {cand['iv']:.0f}%")
            if abs(cand["atm_dist_pct"]) < 1:
                unusual_flags.append("ATM Strike")

            scored.append({
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "name": sym_name,
                "expiry": nearest_expiry,
                "strike": cand["strike"],
                "type": cand["opt_type"],
                "ltp": round(cand["ltp"], 2),
                "ltp_change_pct": round(cand["ltp_chg_pct"], 2),
                "oi": cand["oi"],
                "oi_change_pct": round(cand["oi_change_pct"], 2),
                "volume": cand["volume"],
                "vol_3day_avg": round(vol_3day_avg, 0),
                "vol_spike_ratio": round(vol_spike_ratio, 2),
                "iv": round(cand["iv"], 2) if cand["iv"] else None,
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                "greek_interpretation": greek_interp,
                "spot": round(spot, 2),
                "spot_change_pct": round(ul_chg_pct, 2),
                "vwap_dev_pct": round(vwap_dev, 2),
                "above_ema20": above_ema,
                "atm_dist_pct": round(cand["atm_dist_pct"], 2),
                "lis": lis,
                "signal": signal,
                "conviction": conviction,
                "unusual_flags": unusual_flags,
            })

        if not scored:
            return None

        # Return the single highest-LIS contract
        scored.sort(key=lambda x: x["lis"], reverse=True)
        return scored[0]

    # ── Public: Full scan (180 stocks, 1 per stock) ───────────────

    def scan_all(
        self,
        symbols: Optional[List[str]] = None,
        min_lis: float = 0,
        opt_type_filter: Optional[str] = None,
        strike_count: int = 10,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Scan all FNO stocks, return ONE best strike per stock.
        Processes in batches to respect API rate limits.

        progress_callback(scanned, total, current_symbol, flagged_row|None, error|None)
        """
        if not self._is_authenticated():
            return {
                "success": False,
                "error": "Not authenticated with Fyers API",
                "flagged": [],
            }

        watch = filter_valid_symbols(symbols or ALL_FNO_WATCHLIST)
        total = len(watch)
        all_flagged: List[Dict] = []
        errors: List[str] = []
        scanned = 0
        rate_limited_skips = 0
        aborted_rate_limit = False
        BATCH_SIZE = 10
        BATCH_SLEEP = 0.5  # seconds between batches

        def _progress(sym: str, flagged_row=None, err=None):
            if progress_callback:
                try:
                    progress_callback(scanned, total, sym, flagged_row, err)
                except Exception:
                    pass

        for batch_start in range(0, len(watch), BATCH_SIZE):
            batch = watch[batch_start: batch_start + BATCH_SIZE]
            for sym in batch:
                if not is_valid_symbol(sym):
                    scanned += 1
                    _progress(sym, err="invalid_symbol")
                    continue
                try:
                    underlying = self._get_underlying_data(sym)
                    if not underlying:
                        scanned += 1
                        _progress(sym, err="no_underlying")
                        continue

                    best = self._process_option_chain(sym, underlying, strike_count)
                    if best is None:
                        scanned += 1
                        _progress(sym)
                        continue

                    # Apply filters
                    if opt_type_filter and best["type"] != opt_type_filter:
                        scanned += 1
                        _progress(sym)
                        continue
                    if min_lis > 0 and best["lis"] < min_lis:
                        scanned += 1
                        _progress(sym)
                        continue

                    all_flagged.append(best)
                    scanned += 1
                    _progress(sym, flagged_row=best)

                except Exception as exc:
                    msg = str(exc)
                    if "invalid symbol" in msg.lower():
                        mark_invalid_symbol(sym)
                    try:
                        from app.services.rate_limiter import is_rate_limit_error
                        if is_rate_limit_error(exc) or is_rate_limit_error(msg):
                            rate_limited_skips += 1
                    except Exception:
                        pass
                    logger.warning(f"Radar scan error for {sym}: {exc}")
                    errors.append(f"{sym}: {msg}")
                    scanned += 1
                    _progress(sym, err=msg)

            # Rate-limit protection between batches (longer when under pressure)
            if batch_start + BATCH_SIZE < len(watch):
                try:
                    from app.services.rate_limiter import get_fyers_limiter
                    lim = get_fyers_limiter()
                    if lim.in_cooldown:
                        time.sleep(min(lim.cooldown_remaining, 30))
                        # Mark remaining symbols as skipped so progress is honest
                        remaining = watch[batch_start + BATCH_SIZE :]
                        rate_limited_skips += len(remaining)
                        for rsym in remaining:
                            scanned += 1
                            errors.append(f"{rsym}: rate_limited")
                            _progress(rsym, err="rate_limited")
                        aborted_rate_limit = True
                        break
                except Exception:
                    pass
                time.sleep(BATCH_SLEEP)

        all_flagged.sort(key=lambda x: x["lis"], reverse=True)

        result = {
            "success": True,
            "scanned": scanned,
            "universe_requested": total,
            "total_flagged": len(all_flagged),
            "flagged": all_flagged,
            "errors": errors,
            "rate_limited_skips": rate_limited_skips,
            "partial": aborted_rate_limit or scanned < total,
            "completion_pct": round(100.0 * min(scanned, total) / max(total, 1), 1),
            "timestamp": datetime.now().isoformat(),
            "market_hours": self._is_market_hours(),
        }
        self._last_scan = result
        self._last_scan_at = datetime.now()
        self._persist_last_scan()
        return result

    # ── Public: Single symbol option chain with LIS ───────────────

    def get_symbol_flow(
        self,
        symbol: str,
        strike_count: int = 12,
    ) -> Dict[str, Any]:
        if not self._is_authenticated():
            return {"success": False, "error": "Not authenticated", "flagged": []}

        try:
            underlying = self._get_underlying_data(symbol)
            if not underlying:
                return {"success": False, "error": f"Failed to get data for {symbol}", "flagged": []}

            # Get all flagged contracts for this symbol (no 1-per-stock limit)
            chain_resp = self.market_service.get_option_chain(symbol, strike_count)
            spot = chain_resp.get("spot_price") or underlying.get("ltp", 0)
            expiries = chain_resp.get("expiries", [])

            normalized_expiries = [
                e.get("expiry") or e.get("date") or str(e) if isinstance(e, dict) else str(e)
                for e in expiries
            ]

            # Get best contract (reuse _process_option_chain)
            best = self._process_option_chain(symbol, underlying, strike_count)
            flagged = [best] if best else []

            return {
                "success": True,
                "symbol": symbol,
                "name": _sym_name(symbol),
                "underlying": underlying,
                "chain": chain_resp.get("chain", []),
                "spot_price": underlying.get("ltp"),
                "pcr": chain_resp.get("pcr"),
                "india_vix": chain_resp.get("india_vix"),
                "atm_strike": chain_resp.get("atm_strike"),
                "expiries": normalized_expiries,
                "flagged_contracts": flagged,
                "candles_5min": underlying.get("candles_5min", []),
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as exc:
            logger.error(f"Symbol flow error for {symbol}: {exc}")
            return {"success": False, "error": str(exc), "flagged": []}

    # ── Public: Historical candles for chart ─────────────────────

    def get_candles(
        self,
        symbol: str,
        resolution: str = "5",
        days: int = 1,
    ) -> Dict[str, Any]:
        if not self._is_authenticated():
            return {"success": False, "error": "Not authenticated", "candles": []}
        try:
            return self.market_service.get_historical_data(symbol, resolution, days=days)
        except Exception as exc:
            return {"success": False, "error": str(exc), "candles": []}

    # ── Public: Backtest (forward return tracking) ────────────────

    def backtest_signal(
        self,
        symbol: str,
        strike: int,
        opt_type: str,
        signal_timestamp: str,
        forward_minutes: List[int] = None,
    ) -> Dict[str, Any]:
        if forward_minutes is None:
            forward_minutes = [15, 30, 60]

        if not self._is_authenticated():
            return {"success": False, "error": "Not authenticated"}

        try:
            sig_dt = datetime.fromisoformat(signal_timestamp)
            today = datetime.now().date()
            is_today = sig_dt.date() == today

            hist = self.market_service.get_historical_data(
                symbol=symbol,
                resolution="5",
                days=1 if is_today else 2,
            )
            candles = hist.get("candles", [])
            if not candles:
                return {"success": False, "error": "No historical data available"}

            sig_ts = sig_dt.timestamp()
            ref_price = None
            ref_idx = None
            for i, c in enumerate(candles):
                if abs(c["timestamp"] - sig_ts) < 300:
                    ref_price = c["close"]
                    ref_idx = i
                    break

            if ref_price is None:
                ref_price = candles[0]["close"]
                ref_idx = 0

            forward_returns = {}
            for fwd_min in forward_minutes:
                target_ts = sig_ts + fwd_min * 60
                for c in candles[ref_idx:]:
                    if c["timestamp"] >= target_ts:
                        ret = (c["close"] - ref_price) / ref_price * 100
                        forward_returns[f"{fwd_min}min"] = round(ret, 3)
                        break

            return {
                "success": True,
                "symbol": symbol,
                "strike": strike,
                "option_type": opt_type,
                "signal_timestamp": signal_timestamp,
                "ref_price": ref_price,
                "forward_returns": forward_returns,
            }

        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # ── Utility ───────────────────────────────────────────────────

    @staticmethod
    def _is_market_hours() -> bool:
        # Holiday-aware IST market hours (shared util)
        return is_market_open()

    @staticmethod
    def get_watchlist() -> List[Dict[str, str]]:
        return [
            {"symbol": sym, "name": _sym_name(sym)}
            for sym in ALL_FNO_WATCHLIST
        ]


# ── Singleton ─────────────────────────────────────────────────────

_radar_service: Optional[OptionFlowRadarService] = None


def get_radar_service() -> OptionFlowRadarService:
    global _radar_service
    if _radar_service is None:
        _radar_service = OptionFlowRadarService()
    return _radar_service
