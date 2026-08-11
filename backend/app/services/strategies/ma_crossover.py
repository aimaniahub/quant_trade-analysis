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
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pytz

from app.services.fyers_market import get_market_service
from app.services.fno_stocks import (
    get_fno_universe,
    TOP_FNO_STOCKS,
    FNO_INDICES,
    filter_valid_symbols,
    is_valid_symbol,
    mark_invalid_symbol,
)
from app.services.rate_limiter import get_fyers_limiter, is_rate_limit_error
from app.utils.market_hours import is_market_open

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")

# Canonical universe (shared with radar / HV scanner via fno_stocks)
FNO_SYMBOLS: List[str] = filter_valid_symbols(get_fno_universe(include_indices=True))
# Lighter auto-scan set (rate-limit friendly)
TOP_SCAN_SYMBOLS: List[str] = filter_valid_symbols(
    list(dict.fromkeys([*TOP_FNO_STOCKS, *FNO_INDICES]))
)


def _is_invalid_symbol_error(exc_or_msg) -> bool:
    text = str(exc_or_msg).lower()
    return "invalid symbol" in text or "symbol not found" in text

# Fyers resolution strings
TIMEFRAME_MAP = {
    "15min": "15",
    "30min": "30",
    "1H": "60",
    "4H": "240",
    "1D": "D",
}

# Days of history required for each timeframe to get enough candles (min 200 for Trend MA)
# Kept conservative to reduce multi-chunk history fan-out.
HISTORY_DAYS_MAP = {
    "15min": 12,
    "30min": 20,
    "1H": 40,
    "4H": 90,
    "1D": 260,
}


# Default configuration
# Uses 20EMA / 50EMA / 200EMA — standard Indian F&O algo trader setup.
# Auto scan rotates through the FULL universe in chunks (rate-limit safe).
DEFAULT_CONFIG = {
    "ma_short_type": "EMA",
    "ma_short_period": 20,
    "ma_long_type": "EMA",
    "ma_long_period": 50,
    "ma_trend_type": "EMA",
    "ma_trend_period": 200,
    # 3 TFs default (was 5) — full set still allowed via settings UI
    "timeframes": ["15min", "1H", "1D"],
    "proximity_threshold": 0.5,
    "consecutive_candles": 2,
    "cooldown_minutes": 30,
    "scan_batch_size": 1,          # concurrent symbols (keep 1 under rate limits)
    "scan_interval_secs": 180,     # 3 min between rotation chunks
    # False = rotate full FNO universe; True = only TOP list every cycle
    "auto_scan_top_only": False,
    # Symbols per auto-scan cycle when not top_only (covers ~187 in ~6 cycles)
    "auto_scan_chunk_size": 32,
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
        self._semaphore = asyncio.Semaphore(int(self.config.get("scan_batch_size", 1)))
        self._broadcast_cb: Optional[Callable] = None
        self._limiter = get_fyers_limiter()
        self._abort_scan = False  # set True on hard rate-limit to end current pass early
        self._results_lock = threading.Lock()
        # Round-robin cursor over full universe for auto scans
        self._rotation_index = 0

        # Progress tracking state
        self._scan_active = False
        self._scan_progress_total = 0
        self._scan_progress_current = 0
        self._last_scanned_symbol = ""
        self._last_progress_broadcast_ts = 0.0
        self._last_scan_mode = ""
        self._last_scan_chunk: List[str] = []

        # Load persisted state
        self._load_state()
        # Re-bind semaphore if config restored a batch size
        self._semaphore = asyncio.Semaphore(int(self.config.get("scan_batch_size", 1)))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_broadcast_callback(self, fn: Callable):
        """Register a coroutine/function called whenever a crossover is found."""
        self._broadcast_cb = fn

    def update_config(self, new_cfg: Dict):
        self.config.update({k: v for k, v in new_cfg.items() if v is not None})
        self._semaphore = asyncio.Semaphore(int(self.config.get("scan_batch_size", 1)))
        self._save_state()

    def get_config(self) -> Dict:
        return dict(self.config)

    def get_crossovers(self) -> List[Dict]:
        return list(self._crossovers)

    def get_nearing(self) -> List[Dict]:
        return list(self._nearing)

    def get_status(self) -> Dict:
        fyers = self.market_service._get_fyers()
        top_only = bool(self.config.get("auto_scan_top_only", False))
        chunk = int(self.config.get("auto_scan_chunk_size", 32))
        universe = filter_valid_symbols(FNO_SYMBOLS)
        return {
            "running": self._running,
            "market_open": is_market_open(),
            "authenticated": fyers is not None,
            "symbols_tracked": len(universe),
            "auto_scan_symbols": len(TOP_SCAN_SYMBOLS) if top_only else min(chunk, len(universe)),
            "universe_size": len(universe),
            "rotation_index": self._rotation_index,
            "last_scan_mode": self._last_scan_mode,
            "last_scan_chunk_size": len(self._last_scan_chunk),
            "timeframes": self.config["timeframes"],
            "crossovers_count": len(self._crossovers),
            "nearing_count": len(self._nearing),
            "config": self.config,
            "scan_active": self._scan_active,
            "rate_limit_cooldown": self._limiter.cooldown_remaining,
            "scan_progress": {
                "active": self._scan_active,
                "current": self._scan_progress_current,
                "total": self._scan_progress_total,
                "percentage": round((self._scan_progress_current / self._scan_progress_total * 100), 1) if self._scan_progress_total > 0 else 0,
                "last_symbol": self._last_scanned_symbol
            },
            "scan_note": (
                f"Auto-scan rotates through all {len(universe)} symbols "
                f"in chunks of {chunk} every {self.config.get('scan_interval_secs', 180)}s "
                "(manual scan = full universe once)."
                if not top_only
                else f"Auto-scan top-only mode ({len(TOP_SCAN_SYMBOLS)} symbols)."
            ),
        }

    def _next_rotation_chunk(self, universe: List[str], chunk_size: int) -> List[str]:
        """Return next slice of universe and advance rotation cursor."""
        if not universe:
            return []
        n = len(universe)
        chunk_size = max(1, min(chunk_size, n))
        start = self._rotation_index % n
        end = start + chunk_size
        if end <= n:
            chunk = universe[start:end]
        else:
            # wrap around
            chunk = universe[start:] + universe[: end - n]
        self._rotation_index = end % n
        return chunk


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
        """
        Hook: update cache incrementally on new 1-min candle (non-blocking).

        Maintains a rolling close buffer so we can refresh MA snapshots
        without waiting for the next full history scan. Full golden/death
        confirmation still comes from the periodic multi-TF history scan.
        """
        symbol = candle.get("symbol")
        if not symbol:
            return
        close = candle.get("close")
        if close is None:
            return

        if symbol not in self._ma_cache:
            self._ma_cache[symbol] = {}
        cache = self._ma_cache[symbol]
        cache["_last_close"] = close
        cache["_last_ts"] = candle.get("timestamp")

        # Rolling 1-min closes (enough for 200 EMA when stream is live long enough)
        closes = cache.get("_closes_1m")
        if not isinstance(closes, list):
            closes = []
        closes.append(float(close))
        if len(closes) > 260:
            closes = closes[-260:]
        cache["_closes_1m"] = closes

        # Incremental snapshot for short/long/trend on 1-min aggregate
        # (displayed as live context; not a substitute for multi-TF confirmation)
        try:
            short_period = int(self.config.get("ma_short_period", 20))
            long_period = int(self.config.get("ma_long_period", 50))
            trend_period = int(self.config.get("ma_trend_period", 200))
            short_type = self.config.get("ma_short_type", "EMA")
            long_type = self.config.get("ma_long_type", "EMA")
            trend_type = self.config.get("ma_trend_type", "EMA")
            if len(closes) >= long_period:
                cache["live_1m"] = {
                    "ma_short": compute_ma(closes, short_period, short_type),
                    "ma_long": compute_ma(closes, long_period, long_type),
                    "ma_trend": compute_ma(closes, min(trend_period, len(closes)), trend_type)
                    if len(closes) >= trend_period
                    else None,
                    "price": closes[-1],
                    "bars": len(closes),
                    "timestamp": candle.get("timestamp"),
                }
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Scan loop
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Manual trigger scan
    # ------------------------------------------------------------------

    async def trigger_manual_scan(self) -> bool:
        """Manually trigger a full-universe scan immediately in a background task."""
        if self._scan_active:
            return False
        asyncio.create_task(self._full_scan(mode="full"))
        return True

    # ------------------------------------------------------------------
    # Scan loop
    # ------------------------------------------------------------------

    async def _scan_loop(self):
        """Main loop: lighter top-only scan on an interval during market hours."""
        # Startup: only scan if authenticated. Avoid multi-hour spam of
        # "Could not authenticate" when token is missing/expired.
        try:
            if self.market_service._get_fyers() is not None:
                logger.info("[MACrossover] Running initial startup scan (first rotation chunk)...")
                await self._full_scan(mode="auto")
            else:
                logger.warning(
                    "[MACrossover] Skipping startup scan — not authenticated. "
                    "Generate a Fyers token, then start/scan from the UI."
                )
        except Exception as exc:
            logger.error(f"[MACrossover] Initial startup scan error: {exc}", exc_info=True)

        while self._running:
            interval = int(self.config.get("scan_interval_secs", 600))

            if self.market_service._get_fyers() is None:
                logger.warning("[MACrossover] Not authenticated – sleeping 120s")
                await asyncio.sleep(120)
                continue

            if self._limiter.in_cooldown:
                wait = self._limiter.cooldown_remaining
                logger.warning(f"[MACrossover] rate-limit cooldown – sleeping {wait:.0f}s")
                await asyncio.sleep(max(wait, 5))
                continue

            if not is_market_open():
                logger.info("[MACrossover] Market closed – sleeping 60s")
                await asyncio.sleep(60)
                continue

            try:
                # Auto path: rotating full-universe chunks (or top-only if configured)
                await self._full_scan(mode="auto")
            except Exception as exc:
                logger.error(f"[MACrossover] scan error: {exc}", exc_info=True)

            await asyncio.sleep(interval)

    async def _full_scan(self, top_only: bool = False, mode: str = "full"):
        """
        Scan symbols across configured timeframes (rate-limited).

        mode:
          - "auto": rotate chunk of full universe (or top list if auto_scan_top_only)
          - "full": entire universe (manual trigger)
          - "top": TOP_SCAN_SYMBOLS only
        """
        timeframes = self.config.get("timeframes") or ["15min", "1H", "1D"]
        universe = filter_valid_symbols(FNO_SYMBOLS)
        top = filter_valid_symbols(TOP_SCAN_SYMBOLS)

        if mode == "auto":
            if bool(self.config.get("auto_scan_top_only", False)):
                symbols = top
                self._last_scan_mode = "auto_top"
            else:
                chunk_size = int(self.config.get("auto_scan_chunk_size", 32))
                symbols = self._next_rotation_chunk(universe, chunk_size)
                self._last_scan_mode = f"auto_rotate_{len(symbols)}"
        elif mode == "top" or top_only:
            symbols = top
            self._last_scan_mode = "top"
        else:
            symbols = universe
            self._last_scan_mode = "full"

        self._last_scan_chunk = list(symbols)

        crossovers: List[Dict] = []
        nearing: List[Dict] = []
        self._abort_scan = False

        # Initialize progress tracking
        self._scan_active = True
        self._scan_progress_total = len(symbols)
        self._scan_progress_current = 0
        self._last_scanned_symbol = ""
        await self._broadcast_progress()

        logger.info(
            f"[MACrossover] scan start mode={self._last_scan_mode} "
            f"symbols={len(symbols)}/{len(universe)} tfs={timeframes} "
            f"rotation_idx={self._rotation_index}"
        )

        # Sequential batches via semaphore (default 1) to respect rate limiter
        tasks = [
            self._scan_symbol(symbol, timeframes, crossovers, nearing)
            for symbol in symbols
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Always merge into existing state for rotation scans so prior chunks
        # are not wiped. Full manual scan still merges (keeps multi-pass value).
        if crossovers:
            merged = {
                f"{c['symbol']}|{c['timeframe']}|{c['type']}": c
                for c in self._crossovers
            }
            for c in crossovers:
                merged[f"{c['symbol']}|{c['timeframe']}|{c['type']}"] = c
            self._crossovers = sorted(
                merged.values(), key=lambda x: x["timestamp"], reverse=True
            )[:200]
        if nearing:
            merged_n = {
                f"{c['symbol']}|{c['timeframe']}": c for c in self._nearing
            }
            for c in nearing:
                merged_n[f"{c['symbol']}|{c['timeframe']}"] = c
            self._nearing = sorted(
                merged_n.values(), key=lambda x: abs(x.get("distance_pct", 0))
            )[:100]

        # Reset progress tracking
        self._scan_active = False
        self._scan_progress_current = len(symbols)
        await self._broadcast_progress()

        self._save_state()

        logger.info(
            f"[MACrossover] Scan complete – {len(self._crossovers)} crossovers, "
            f"{len(self._nearing)} nearing abort={self._abort_scan}"
        )

    async def _scan_symbol(
        self,
        symbol: str,
        timeframes: List[str],
        crossovers: List[Dict],
        nearing: List[Dict],
    ):
        if self._abort_scan:
            return
        async with self._semaphore:
            if self._abort_scan:
                return
            for tf in timeframes:
                if self._abort_scan:
                    break
                try:
                    result = await self._check_tf(symbol, tf)
                    if result:
                        with self._results_lock:
                            if result["type"] in ("golden_cross", "death_cross"):
                                crossovers.append(result)
                            elif result["type"] == "nearing":
                                nearing.append(result)
                        if result["type"] in ("golden_cross", "death_cross"):
                            await self._maybe_broadcast(result)
                except Exception as exc:
                    if is_rate_limit_error(exc):
                        self._limiter.trip_limit(str(exc))
                        self._abort_scan = True
                        logger.warning("[MACrossover] aborting scan pass due to rate limit")
                        break
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

        # Require the cross to hold for `consecutive_candles` bars (default 2).
        # That means short was on the other side of long `consec` bars ago, and
        # has stayed crossed for the last `consec` bars including the current one.
        consec = max(1, int(consec or 1))

        def _held_cross(above: bool) -> bool:
            """True if short is above/below long for the last `consec` closes."""
            if len(closes) < long_period + consec + 1:
                return False
            # Check current and previous (consec-1) bars all on the same side
            for i in range(consec):
                end = len(closes) - i
                if end < long_period:
                    return False
                window = closes[:end]
                s = compute_ma(window, short_period, short_type)
                l = compute_ma(window, long_period, long_type)
                if s is None or l is None:
                    return False
                if above and not (s > l):
                    return False
                if not above and not (s < l):
                    return False
            # And that the bar before the hold window was on the opposite side
            # (actual flip). If consec==1 this reduces to classic prev/current.
            prior_end = len(closes) - consec
            if prior_end < long_period:
                return False
            prior = closes[:prior_end]
            ps = compute_ma(prior, short_period, short_type)
            pl = compute_ma(prior, long_period, long_type)
            if ps is None or pl is None:
                return False
            if above:
                return ps <= pl
            return ps >= pl

        # Golden Cross: short crossed above long and held
        if _held_cross(above=True):
            key = f"{symbol}_{tf}_golden"
            if self._is_cooldown_clear(key):
                self._set_cooldown(key)
                return {
                    **base,
                    "type": "golden_cross",
                    "signal": "BUY",
                    "confirmed_bars": consec,
                }

        # Death Cross: short crossed below long and held
        if _held_cross(above=False):
            key = f"{symbol}_{tf}_death"
            if self._is_cooldown_clear(key):
                self._set_cooldown(key)
                return {
                    **base,
                    "type": "death_cross",
                    "signal": "SELL",
                    "confirmed_bars": consec,
                }

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
        # Skip blacklisted / known-invalid symbols immediately (no Fyers calls)
        if not is_valid_symbol(symbol):
            return None

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
        delay = 1.5
        
        for from_date, to_date in chunks:
            if self._abort_scan:
                return None
            success = False
            for attempt in range(max_retries):
                try:
                    # Process-wide limiter shared with radar / other scanners
                    await self._limiter.acquire()
                    result = await asyncio.to_thread(
                        self.market_service.get_historical_data,
                        symbol,
                        resolution,
                        from_date,
                        to_date,
                        0  # days won't be used since from_date is not None
                    )
                    if not result.get("success"):
                        err = result.get("error", "Unknown")
                        if is_rate_limit_error(err):
                            self._limiter.trip_limit(err)
                            self._abort_scan = True
                            return None
                        # Invalid symbol: blacklist and stop all retries/chunks
                        if _is_invalid_symbol_error(err):
                            mark_invalid_symbol(symbol)
                            logger.warning(
                                f"[MACrossover] blacklisting invalid symbol {symbol}"
                            )
                            return None
                        raise Exception(f"Fyers error: {err}")
                    candles = result.get("candles") or []
                    all_candles.extend(candles)
                    self._limiter.clear_soft()
                    success = True
                    break
                except Exception as exc:
                    if _is_invalid_symbol_error(exc):
                        mark_invalid_symbol(symbol)
                        logger.warning(
                            f"[MACrossover] blacklisting invalid symbol {symbol}: {exc}"
                        )
                        return None
                    logger.warning(
                        f"[MACrossover] fetch {symbol}/{resolution} chunk {from_date} to {to_date} attempt {attempt+1}: {exc}"
                    )
                    if is_rate_limit_error(exc):
                        self._limiter.trip_limit(str(exc))
                        self._abort_scan = True
                        return None
                    if attempt < max_retries - 1:
                        await asyncio.sleep(delay)
                        delay *= 2
            
            if not success:
                # If any chunk fails completely after retries, return None to avoid partial/corrupted data
                return None

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

        # Also push actionable crosses onto the shared signal bus / alerts WS
        try:
            etype = event.get("type")
            if etype in ("golden_cross", "death_cross"):
                from app.services.signal_bus import get_signal_bus
                signal = event.get("signal") or ("BUY" if etype == "golden_cross" else "SELL")
                symbol = event.get("symbol")
                tf = event.get("timeframe")
                get_signal_bus().publish(
                    source="ma_crossover",
                    message=f"{signal} {symbol} {tf} ({etype.replace('_', ' ')})",
                    level="signal",
                    symbol=symbol,
                    score=None,
                    meta={
                        "type": etype,
                        "timeframe": tf,
                        "price": event.get("price"),
                        "ma_short": event.get("ma_short"),
                        "ma_long": event.get("ma_long"),
                    },
                )
        except Exception as exc:
            logger.debug(f"[MACrossover] signal bus publish failed: {exc}")

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
                # Only restore known keys; fill new keys from defaults
                for k, v in saved_cfg.items():
                    if k in DEFAULT_CONFIG:
                        self.config[k] = v
                for k, v in DEFAULT_CONFIG.items():
                    self.config.setdefault(k, v)

                # One-time migration: old installs scanned 5 TFs × full universe → 429s
                tfs = self.config.get("timeframes") or []
                if len(tfs) >= 5 and not saved_cfg.get("keep_aggressive_scan"):
                    logger.info(
                        "[MACrossover] Migrating config: timeframes 5→3, rotate full universe"
                    )
                    self.config["timeframes"] = list(DEFAULT_CONFIG["timeframes"])
                    self.config["auto_scan_top_only"] = False
                    self.config["auto_scan_chunk_size"] = DEFAULT_CONFIG["auto_scan_chunk_size"]
                    self.config["scan_interval_secs"] = DEFAULT_CONFIG["scan_interval_secs"]
                    self.config["scan_batch_size"] = 1
                # Migrate sticky top-only from earlier rate-limit patch
                if saved_cfg.get("auto_scan_top_only") is True and not saved_cfg.get(
                    "keep_top_only"
                ):
                    self.config["auto_scan_top_only"] = False
                    self.config.setdefault(
                        "auto_scan_chunk_size", DEFAULT_CONFIG["auto_scan_chunk_size"]
                    )
                    self.config["scan_interval_secs"] = min(
                        int(self.config.get("scan_interval_secs") or 600), 180
                    )
                    logger.info(
                        "[MACrossover] Migrating config: top-only → full universe rotation"
                    )

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
