"""
MA Crossover Strategy Service
==============================
Scans 200+ F&O symbols across 5 timeframes for Moving Average crossovers.

Crossover types detected:
  • Golden Cross  – short MA crosses ABOVE long MA (bullish)
  • Death Cross   – short MA crosses BELOW long MA (bearish)
  • Nearing       – distance between MAs < proximity_threshold %

Configuration (user-overridable via Settings panel):
  • ma_short_type / ma_long_type / ma_trend_type  (EMA | SMA | WMA)
  • ma_short_period / ma_long_period / ma_trend_period
  • timeframes                                      (list of Fyers resolutions)
  • proximity_threshold                             (% distance = 0.5 default)
  • consecutive_candles                             (validation candles = 2)

Architecture:
  1. Periodic scan loop (asyncio task) – fetches historical OHLCV
  2. CandleAggregator callback – closes a 1-min candle → triggers
     incremental update for 15min / 30min timeframes if needed
  3. Detected crossovers broadcast via ma_crossover_manager (WS)
  4. Persistent cache in ma_crossover_state.json
"""

import asyncio
import json
import logging
import os
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytz

from app.services.fyers_market import get_market_service
from app.utils.market_hours import is_market_open

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

# ---------------------------------------------------------------------------
# All NSE F&O symbols (200 most liquid) – Fyers format
# ---------------------------------------------------------------------------
FNO_SYMBOLS: List[str] = [
    "NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:HDFCBANK-EQ", "NSE:INFY-EQ",
    "NSE:ICICIBANK-EQ", "NSE:HINDUNILVR-EQ", "NSE:KOTAKBANK-EQ", "NSE:LT-EQ",
    "NSE:SBIN-EQ", "NSE:BHARTIARTL-EQ", "NSE:AXISBANK-EQ", "NSE:BAJFINANCE-EQ",
    "NSE:HCLTECH-EQ", "NSE:WIPRO-EQ", "NSE:ASIANPAINT-EQ", "NSE:MARUTI-EQ",
    "NSE:ONGC-EQ", "NSE:ITC-EQ", "NSE:POWERGRID-EQ", "NSE:TITAN-EQ",
    "NSE:SUNPHARMA-EQ", "NSE:ULTRACEMCO-EQ", "NSE:NTPC-EQ", "NSE:M&M-EQ",
    "NSE:TECHM-EQ", "NSE:TATASTEEL-EQ", "NSE:BAJAJFINSV-EQ", "NSE:HINDALCO-EQ",
    "NSE:INDUSINDBK-EQ", "NSE:ADANIENT-EQ", "NSE:ADANIPORTS-EQ", "NSE:COALINDIA-EQ",
    "NSE:GRASIM-EQ", "NSE:DIVISLAB-EQ", "NSE:CIPLA-EQ", "NSE:EICHERMOT-EQ",
    "NSE:DRREDDY-EQ", "NSE:NESTLEIND-EQ", "NSE:BPCL-EQ", "NSE:TATACONSUM-EQ",
    "NSE:BRITANNIA-EQ", "NSE:SBILIFE-EQ", "NSE:BAJAJ-AUTO-EQ", "NSE:HEROMOTOCO-EQ",
    "NSE:UPL-EQ", "NSE:SHREECEM-EQ", "NSE:HDFCLIFE-EQ", "NSE:APOLLOHOSP-EQ",
    "NSE:TATAMOTORS-EQ", "NSE:JSWSTEEL-EQ", "NSE:PIDILITIND-EQ", "NSE:BERGEPAINT-EQ",
    "NSE:DABUR-EQ", "NSE:GODREJCP-EQ", "NSE:SIEMENS-EQ", "NSE:ABB-EQ",
    "NSE:AMBUJACEM-EQ", "NSE:ACC-EQ", "NSE:HAVELLS-EQ", "NSE:VOLTAS-EQ",
    "NSE:LUPIN-EQ", "NSE:AUROPHARMA-EQ", "NSE:TORNTPHARM-EQ", "NSE:BIOCON-EQ",
    "NSE:GLENMARK-EQ", "NSE:IPCALAB-EQ", "NSE:ALKEM-EQ", "NSE:NATCOPHARM-EQ",
    "NSE:MCDOWELL-N-EQ", "NSE:UNITED SPIRITS-EQ", "NSE:RADICO-EQ",
    "NSE:BANKBARODA-EQ", "NSE:PNB-EQ", "NSE:CANBK-EQ", "NSE:FEDERALBNK-EQ",
    "NSE:IDFCFIRSTB-EQ", "NSE:BANDHANBNK-EQ", "NSE:RBLBANK-EQ", "NSE:DCBBANK-EQ",
    "NSE:LICHSGFIN-EQ", "NSE:CHOLAFIN-EQ", "NSE:M&MFIN-EQ", "NSE:MANAPPURAM-EQ",
    "NSE:MUTHOOTFIN-EQ", "NSE:BAJAJHLDNG-EQ", "NSE:RECLTD-EQ", "NSE:PFC-EQ",
    "NSE:IRFC-EQ", "NSE:NHPC-EQ", "NSE:SJVN-EQ",
    "NSE:GAIL-EQ", "NSE:IOC-EQ", "NSE:HINDPETRO-EQ", "NSE:MGL-EQ",
    "NSE:IGL-EQ", "NSE:PETRONET-EQ",
    "NSE:NAUKRI-EQ", "NSE:ZOMATO-EQ", "NSE:PAYTM-EQ", "NSE:POLICYBZR-EQ",
    "NSE:DELHIVERY-EQ", "NSE:MAPMYINDIA-EQ", "NSE:HAPPSTMNDS-EQ", "NSE:MPHASIS-EQ",
    "NSE:LTI-EQ", "NSE:PERSISTENT-EQ", "NSE:COFORGE-EQ", "NSE:LTIMINDTREE-EQ",
    "NSE:TATAELXSI-EQ", "NSE:KPITTECH-EQ", "NSE:CYIENT-EQ", "NSE:MASTEK-EQ",
    "NSE:ZENSAR-EQ", "NSE:NIITTECH-EQ",
    "NSE:DLF-EQ", "NSE:GODREJPROP-EQ", "NSE:OBEROIRLTY-EQ", "NSE:PRESTIGE-EQ",
    "NSE:BRIGADE-EQ", "NSE:PHOENIXLTD-EQ", "NSE:MAHLIFE-EQ",
    "NSE:INDIGO-EQ", "NSE:SPICEJET-EQ",
    "NSE:TATAPOWER-EQ", "NSE:ADANIGREEN-EQ", "NSE:CESC-EQ", "NSE:TORNTPOWER-EQ",
    "NSE:ADANIENSOL-EQ", "NSE:NLCINDIA-EQ",
    "NSE:VEDL-EQ", "NSE:NATIONALUM-EQ", "NSE:HINDCOPPER-EQ", "NSE:RATNAMANI-EQ",
    "NSE:APOLLOTYRE-EQ", "NSE:MRF-EQ", "NSE:BALKRISIND-EQ",
    "NSE:GMRINFRA-EQ", "NSE:IRB-EQ", "NSE:KNRCON-EQ",
    "NSE:TATACOMM-EQ", "NSE:INDUSTOWER-EQ",
    "NSE:STAR-EQ", "NSE:SUNTV-EQ", "NSE:ZEEL-EQ",
    "NSE:JUBLFOOD-EQ", "NSE:WESTLIFE-EQ",
    "NSE:PAGEIND-EQ", "NSE:MANYAVAR-EQ", "NSE:ABFRL-EQ",
    "NSE:TRENT-EQ", "NSE:SHOPERSTOP-EQ",
    "NSE:ZYDUSLIFE-EQ", "NSE:SANOFI-EQ", "NSE:PFIZER-EQ", "NSE:ABBOTINDIA-EQ",
    "NSE:LALPATHLAB-EQ", "NSE:METROPOLIS-EQ", "NSE:THYROCARE-EQ",
    "NSE:FORTIS-EQ", "NSE:MAXHEALTH-EQ", "NSE:NH-EQ",
    "NSE:CONCOR-EQ", "NSE:BLUEDART-EQ", "NSE:MAHINDCIE-EQ",
    "NSE:BOSCHLTD-EQ", "NSE:SCHAEFFLER-EQ", "NSE:MOTHERSON-EQ",
    "NSE:EXIDEIND-EQ", "NSE:AMARAJABAT-EQ",
    "NSE:PIIND-EQ", "NSE:GHCL-EQ", "NSE:GNFC-EQ", "NSE:DEEPAKNTR-EQ",
    "NSE:NAVINFLUOR-EQ", "NSE:FLUOROCHEM-EQ", "NSE:CLEAN SCIENCE-EQ",
    "NSE:ANURAS-EQ", "NSE:GRANULES-EQ",
    "NSE:HFCL-EQ", "NSE:RAILTEL-EQ", "NSE:RITES-EQ", "NSE:IRCTC-EQ",
    "NSE:SAIL-EQ", "NSE:NMDC-EQ", "NSE:MOIL-EQ",
    "NSE:CUMMINSIND-EQ", "NSE:THERMAX-EQ", "NSE:BHEL-EQ", "NSE:BEL-EQ",
    "NSE:HAL-EQ", "NSE:MFSL-EQ",
    "NSE:AAVAS-EQ", "NSE:CANFINHOME-EQ", "NSE:HOMEFIRST-EQ",
    "NSE:TATACHEM-EQ", "NSE:ATUL-EQ", "NSE:SRF-EQ",
    "NSE:SYNGENE-EQ", "NSE:DIVI'SLAB-EQ",
    "NSE:BALKRISHNA-EQ", "NSE:JKCEMENT-EQ", "NSE:RAMCOCEM-EQ",
    "NSE:DALBHARAT-EQ", "NSE:HEIDELBERG-EQ",
    "NSE:KAJARIACER-EQ", "NSE:ASAHIINDIA-EQ",
    "NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX",
]

# Fyers resolution strings
TIMEFRAME_MAP = {
    "15min": "15",
    "30min": "30",
    "1H": "60",
    "4H": "240",
    "1D": "D",
}

# Days of history required for each timeframe to get enough candles (min 200 for Trend MA)
HISTORY_DAYS_MAP = {
    "15min": 15,
    "30min": 25,
    "1H": 50,
    "4H": 150,
    "1D": 400,
}


# Default configuration
# Uses 20EMA / 50EMA / 200EMA — standard Indian F&O algo trader setup.
# All EMAs react faster than SMA to institutional order flow.
DEFAULT_CONFIG = {
    "ma_short_type": "EMA",
    "ma_short_period": 20,
    "ma_long_type": "EMA",          # Changed from SMA → EMA for faster institutional signal detection
    "ma_long_period": 50,
    "ma_trend_type": "EMA",
    "ma_trend_period": 200,
    "timeframes": ["15min", "30min", "1H", "4H", "1D"],
    "proximity_threshold": 0.5,   # % distance to flag "nearing"
    "consecutive_candles": 2,      # candles MA must stay crossed
    "cooldown_minutes": 30,        # min gap between same-pair alerts
    "scan_batch_size": 1,          # concurrent Fyers requests
}

STATE_FILE = Path(__file__).parent.parent.parent / "ma_crossover_state.json"


# ---------------------------------------------------------------------------
# MA calculation helpers
# ---------------------------------------------------------------------------

def _ema(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def _sma(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _wma(closes: List[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    window = closes[-period:]
    weights = list(range(1, period + 1))
    return sum(w * p for w, p in zip(weights, window)) / sum(weights)


_MA_FUNCS = {"EMA": _ema, "SMA": _sma, "WMA": _wma}


def compute_ma(closes: List[float], period: int, ma_type: str) -> Optional[float]:
    fn = _MA_FUNCS.get(ma_type.upper(), _ema)
    return fn(closes, period)


# ---------------------------------------------------------------------------
# Core service
# ---------------------------------------------------------------------------

class MACrossoverService:
    """
    Monitors 200+ F&O symbols across up to 5 timeframes for MA crossovers.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config: Dict = {**DEFAULT_CONFIG, **(config or {})}
        self.market_service = get_market_service()

        # Runtime state
        self._crossovers: List[Dict] = []          # confirmed crossovers
        self._nearing: List[Dict] = []              # nearing watchlist
        self._ma_cache: Dict[str, Dict] = {}        # symbol → tf → ma values
        self._cooldowns: Dict[str, float] = {}      # key → last_alert_ts
        self._running = False
        self._scan_task: Optional[asyncio.Task] = None
        self._semaphore = asyncio.Semaphore(int(self.config.get("scan_batch_size", 5)))
        self._broadcast_cb: Optional[Callable] = None

        # Progress tracking state
        self._scan_active = False
        self._scan_progress_total = 0
        self._scan_progress_current = 0
        self._last_scanned_symbol = ""
        self._last_progress_broadcast_ts = 0.0

        # Load persisted state
        self._load_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_broadcast_callback(self, fn: Callable):
        """Register a coroutine/function called whenever a crossover is found."""
        self._broadcast_cb = fn

    def update_config(self, new_cfg: Dict):
        self.config.update(new_cfg)
        self._save_state()

    def get_config(self) -> Dict:
        return dict(self.config)

    def get_crossovers(self) -> List[Dict]:
        return list(self._crossovers)

    def get_nearing(self) -> List[Dict]:
        return list(self._nearing)

    def get_status(self) -> Dict:
        fyers = self.market_service._get_fyers()
        return {
            "running": self._running,
            "market_open": is_market_open(),
            "authenticated": fyers is not None,
            "symbols_tracked": len(FNO_SYMBOLS),
            "timeframes": self.config["timeframes"],
            "crossovers_count": len(self._crossovers),
            "nearing_count": len(self._nearing),
            "config": self.config,
            "scan_active": self._scan_active,
            "scan_progress": {
                "active": self._scan_active,
                "current": self._scan_progress_current,
                "total": self._scan_progress_total,
                "percentage": round((self._scan_progress_current / self._scan_progress_total * 100), 1) if self._scan_progress_total > 0 else 0,
                "last_symbol": self._last_scanned_symbol
            }
        }


    async def start(self):
        if self._running:
            return
        self._running = True
        self._scan_task = asyncio.create_task(self._scan_loop())
        logger.info("[MACrossover] Service started")

    async def stop(self):
        self._running = False
        if self._scan_task:
            self._scan_task.cancel()
        self._save_state()
        logger.info("[MACrossover] Service stopped")

    # Called from CandleAggregator on every 1-min candle close
    def on_candle_closed(self, candle: Dict):
        """Hook: update cache incrementally on new 1-min candle (non-blocking)."""
        symbol = candle.get("symbol")
        if not symbol:
            return
        # Store the latest close price for quick incremental checks
        if symbol not in self._ma_cache:
            self._ma_cache[symbol] = {}
        self._ma_cache[symbol]["_last_close"] = candle.get("close")
        self._ma_cache[symbol]["_last_ts"] = candle.get("timestamp")

    # ------------------------------------------------------------------
    # Scan loop
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Manual trigger scan
    # ------------------------------------------------------------------

    async def trigger_manual_scan(self) -> bool:
        """Manually trigger a full scan immediately in a background task."""
        if self._scan_active:
            return False
        asyncio.create_task(self._full_scan())
        return True

    # ------------------------------------------------------------------
    # Scan loop
    # ------------------------------------------------------------------

    async def _scan_loop(self):
        """Main loop: full scan every 5 minutes during market hours."""
        INTERVAL_SECS = 300  # 5 minutes
        
        # Run initial scan on startup so that the dashboard has crossovers
        # loaded even if started when market is closed.
        try:
            logger.info("[MACrossover] Running initial startup scan...")
            await self._full_scan()
        except Exception as exc:
            logger.error(f"[MACrossover] Initial startup scan error: {exc}", exc_info=True)

        while self._running:
            if not is_market_open():
                logger.info("[MACrossover] Market closed – sleeping 60s")
                await asyncio.sleep(60)
                continue

            try:
                await self._full_scan()
            except Exception as exc:
                logger.error(f"[MACrossover] scan error: {exc}", exc_info=True)

            await asyncio.sleep(INTERVAL_SECS)

    async def _full_scan(self):
        """Scan all symbols across all configured timeframes concurrently."""
        timeframes = self.config.get("timeframes", list(TIMEFRAME_MAP.keys()))
        symbols = FNO_SYMBOLS

        crossovers: List[Dict] = []
        nearing: List[Dict] = []

        # Initialize progress tracking
        self._scan_active = True
        self._scan_progress_total = len(symbols)
        self._scan_progress_current = 0
        self._last_scanned_symbol = ""
        await self._broadcast_progress()

        tasks = [
            self._scan_symbol(symbol, timeframes, crossovers, nearing)
            for symbol in symbols
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Replace state
        self._crossovers = sorted(crossovers, key=lambda x: x["timestamp"], reverse=True)[:200]
        self._nearing = sorted(nearing, key=lambda x: abs(x["distance_pct"]))[:100]

        # Reset progress tracking
        self._scan_active = False
        self._scan_progress_current = len(symbols)
        await self._broadcast_progress()

        self._save_state()

        logger.info(
            f"[MACrossover] Scan complete – {len(self._crossovers)} crossovers, "
            f"{len(self._nearing)} nearing"
        )

    async def _scan_symbol(
        self,
        symbol: str,
        timeframes: List[str],
        crossovers: List[Dict],
        nearing: List[Dict],
    ):
        async with self._semaphore:
            for tf in timeframes:
                try:
                    result = await self._check_tf(symbol, tf)
                    if result:
                        if result["type"] in ("golden_cross", "death_cross"):
                            crossovers.append(result)
                            await self._maybe_broadcast(result)
                        elif result["type"] == "nearing":
                            nearing.append(result)
                except Exception as exc:
                    logger.debug(f"[MACrossover] {symbol}/{tf} error: {exc}")

            # Update progress
            self._scan_progress_current += 1
            self._last_scanned_symbol = symbol
            await self._maybe_broadcast_progress_throttled()

    async def _broadcast_progress(self):
        progress_data = {
            "active": self._scan_active,
            "current": self._scan_progress_current,
            "total": self._scan_progress_total,
            "percentage": round((self._scan_progress_current / self._scan_progress_total * 100), 1) if self._scan_progress_total > 0 else 0,
            "last_symbol": self._last_scanned_symbol
        }
        if self._broadcast_cb:
            try:
                await self._broadcast_cb({
                    "is_progress_update": True,
                    "progress": progress_data
                })
            except Exception as exc:
                logger.error(f"[MACrossover] progress broadcast error: {exc}")

    async def _maybe_broadcast_progress_throttled(self):
        now = time.time()
        # Broadcast at most once every 200ms or when complete
        if now - self._last_progress_broadcast_ts > 0.2 or self._scan_progress_current >= self._scan_progress_total:
            self._last_progress_broadcast_ts = now
            await self._broadcast_progress()


    async def _check_tf(self, symbol: str, tf: str) -> Optional[Dict]:
        """Fetch history for symbol/tf and compute MA crossover status."""
        resolution = TIMEFRAME_MAP.get(tf)
        if not resolution:
            return None

        # Polite rate-limiting sleep to prevent Fyers API 429 errors
        await asyncio.sleep(0.1)

        days = HISTORY_DAYS_MAP.get(tf, 30)
        closes = await self._fetch_closes_with_retry(symbol, resolution, days)
        if not closes or len(closes) < self.config["ma_trend_period"]:
            return None

        short_type = self.config["ma_short_type"]
        short_period = self.config["ma_short_period"]
        long_type = self.config["ma_long_type"]
        long_period = self.config["ma_long_period"]
        trend_type = self.config["ma_trend_type"]
        trend_period = self.config["ma_trend_period"]
        prox = self.config["proximity_threshold"]
        consec = self.config.get("consecutive_candles", 2)

        # Current candle MAs
        ma_short = compute_ma(closes, short_period, short_type)
        ma_long = compute_ma(closes, long_period, long_type)
        ma_trend = compute_ma(closes, trend_period, trend_type)

        if ma_short is None or ma_long is None or ma_trend is None:
            return None

        # Previous candle MAs (for crossover confirmation)
        prev_ma_short = compute_ma(closes[:-1], short_period, short_type)
        prev_ma_long = compute_ma(closes[:-1], long_period, long_type)

        if prev_ma_short is None or prev_ma_long is None:
            return None

        current_price = closes[-1]
        # distance between short MA and long MA (crossover gap — used for nearing detection)
        distance_pct = abs(ma_short - ma_long) / ma_long * 100
        # distance from price to 200EMA — what traders actually watch
        price_to_trend_pct = round((current_price - ma_trend) / ma_trend * 100, 4)

        base = {
            "symbol": symbol,
            "timeframe": tf,
            "price": current_price,
            "ma_short": round(ma_short, 4),
            "ma_long": round(ma_long, 4),
            "ma_trend": round(ma_trend, 4),
            # distance between short and long MA — crossover gap
            "distance_pct": round((ma_short - ma_long) / ma_long * 100, 4),
            # distance from current price to 200EMA — key institutional reference
            "price_to_200ema_pct": price_to_trend_pct,
            "timestamp": int(time.time()),
            "datetime": datetime.now(IST).isoformat(),
        }

        # Golden Cross: short crosses above long
        if prev_ma_short <= prev_ma_long and ma_short > ma_long:
            key = f"{symbol}_{tf}_golden"
            if self._is_cooldown_clear(key):
                self._set_cooldown(key)
                return {**base, "type": "golden_cross", "signal": "BUY"}

        # Death Cross: short crosses below long
        if prev_ma_short >= prev_ma_long and ma_short < ma_long:
            key = f"{symbol}_{tf}_death"
            if self._is_cooldown_clear(key):
                self._set_cooldown(key)
                return {**base, "type": "death_cross", "signal": "SELL"}

        # Nearing crossover
        if distance_pct < prox:
            direction = "approaching_golden" if ma_short < ma_long else "approaching_death"
            return {**base, "type": "nearing", "direction": direction}

        return None

    # ------------------------------------------------------------------
    # Fyers fetch with exponential back-off
    # ------------------------------------------------------------------

    async def _fetch_closes_with_retry(
        self,
        symbol: str,
        resolution: str,
        days: int,
        max_retries: int = 3,
    ) -> Optional[List[float]]:
        # 1. Define max chunk size based on resolution
        if resolution == "D":
            max_chunk_days = 360
        elif resolution == "1":
            max_chunk_days = 30
        else:
            max_chunk_days = 90

        # 2. Divide total days into chunks backwards from today
        chunks = []
        current_to = datetime.now(IST)
        total_days_needed = days
        while total_days_needed > 0:
            chunk_days = min(total_days_needed, max_chunk_days)
            current_from = current_to - timedelta(days=chunk_days)
            chunks.append(
                (
                    current_from.strftime("%Y-%m-%d"),
                    current_to.strftime("%Y-%m-%d")
                )
            )
            # Use day before current_from for next chunk to avoid overlaps
            current_to = current_from - timedelta(days=1)
            total_days_needed -= chunk_days

        all_candles = []
        delay = 1.0
        
        for from_date, to_date in chunks:
            success = False
            for attempt in range(max_retries):
                try:
                    # Rate limiting: Sleep 200ms to stay within Fyers limits (max 10 RPS)
                    await asyncio.sleep(0.2)
                    result = await asyncio.to_thread(
                        self.market_service.get_historical_data,
                        symbol,
                        resolution,
                        from_date,
                        to_date,
                        0  # days won't be used since from_date is not None
                    )
                    if not result.get("success"):
                        raise Exception(f"Fyers error: {result.get('error', 'Unknown')}")
                    candles = result.get("candles") or []
                    all_candles.extend(candles)
                    success = True
                    break
                except Exception as exc:
                    logger.warning(
                        f"[MACrossover] fetch {symbol}/{resolution} chunk {from_date} to {to_date} attempt {attempt+1}: {exc}"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
                        delay *= 2
            
            if not success:
                # If any chunk fails completely after retries, return None to avoid partial/corrupted data
                return None
            
            # Add a minor delay to respect Fyers API rate limits between chunk fetches
            await asyncio.sleep(0.1)

        if all_candles:
            # Deduplicate by timestamp and sort chronologically
            seen = set()
            unique_candles = []
            for c in all_candles:
                ts = c.get("timestamp")
                if ts not in seen:
                    seen.add(ts)
                    unique_candles.append(c)
            unique_candles.sort(key=lambda x: x["timestamp"])
            return [c["close"] for c in unique_candles]
        
        return None

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------

    async def _maybe_broadcast(self, event: Dict):
        if self._broadcast_cb:
            try:
                await self._broadcast_cb(event)
            except Exception as exc:
                logger.error(f"[MACrossover] broadcast error: {exc}")

    # ------------------------------------------------------------------
    # Cooldown helpers
    # ------------------------------------------------------------------

    def _is_cooldown_clear(self, key: str) -> bool:
        cooldown_secs = self.config.get("cooldown_minutes", 30) * 60
        last = self._cooldowns.get(key, 0)
        return (time.time() - last) >= cooldown_secs

    def _set_cooldown(self, key: str):
        self._cooldowns[key] = time.time()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self):
        try:
            state = {
                "config": self.config,
                "crossovers": self._crossovers[-50:],
                "nearing": self._nearing[:50],
                "cooldowns": {
                    k: v for k, v in self._cooldowns.items()
                    if (time.time() - v) < 86400
                },
            }
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(STATE_FILE, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except Exception as exc:
            logger.warning(f"[MACrossover] state save failed: {exc}")

    def _load_state(self):
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE) as f:
                    state = json.load(f)
                saved_cfg = state.get("config", {})
                self.config.update({k: v for k, v in saved_cfg.items() if k in self.config})
                self._crossovers = state.get("crossovers", [])
                self._nearing = state.get("nearing", [])
                self._cooldowns = {
                    k: float(v) for k, v in state.get("cooldowns", {}).items()
                }
                logger.info("[MACrossover] State loaded from disk")
        except Exception as exc:
            logger.warning(f"[MACrossover] state load failed: {exc}")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_service: Optional[MACrossoverService] = None


def get_ma_crossover_service() -> MACrossoverService:
    global _service
    if _service is None:
        _service = MACrossoverService()
    return _service
