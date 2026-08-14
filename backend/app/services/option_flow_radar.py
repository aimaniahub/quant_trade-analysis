"""
Option Flow Radar Service v3
============================
Spec: Option_Flow_Radar_Complete_Specification_v3.txt

- Full CE/PE flow matrix + direction-aware LIS momentum
- Greek Quality Score (0–20) as quality filter
- Multi-layer confirmation → Grade A+/A/B/C
- Alert Box (unusual / big-player) separate from Normal Radar
- Hard filters: ATM ≤7%, vol ≥1.5×, |OI| ≥8%
- Performance: light underlying on scan, vol cache, chain-relative baseline
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
from app.services.radar_signal_engine import (
    MAX_ATM_DISTANCE_PCT,
    MIN_VOL_SPIKE,
    MIN_OI_CHANGE_PCT,
    MIN_OPTION_VOLUME,
    classify_signal,
    compute_momentum_score,
    compute_lis_v2,
    compute_greek_quality_score,
    compute_unusual_score,
    evaluate_layers,
    chain_relative_vol_spike,
    count_cluster_hits,
    interpret_greeks,
    build_scored_contract,
)
from app.services.levels import get_levels_service
from app.services.idea_book import get_idea_book, snapshot_from_contract
from app.services.mtf_service import get_mtf_service

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
    Option Flow Radar v3 – multi-layer flow, Greek quality, Alert Box.
    """

    def __init__(self):
        self.market_service = get_market_service()
        self.auth_service = get_auth_service()
        # In-memory cache for 3-day vol averages  {option_symbol: (avg_vol, fetched_at)}
        self._vol_cache: Dict[str, Tuple[float, datetime]] = {}
        self._VOL_CACHE_TTL = 3600  # 1 hour
        # Underlying quote/history short cache (scan speed)
        self._ul_cache: Dict[str, Tuple[Dict[str, Any], datetime]] = {}
        self._UL_CACHE_TTL = 90
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

    def _get_underlying_data(self, symbol: str, *, light: bool = False) -> Dict[str, Any]:
        """
        light=True (scan path): spot only + inferred EMA/VWAP context — fewer API calls.
        light=False (detail): full 5m history for chart + accurate VWAP/EMA.
        """
        now = datetime.now()
        cached = self._ul_cache.get(symbol)
        if cached:
            data, ts = cached
            age = (now - ts).total_seconds()
            if age < self._UL_CACHE_TTL and (light or data.get("candles_5min")):
                return data

        stale = cached[0] if cached else {}
        spot_resp = self.market_service.get_spot_price(symbol)
        ltp = float(spot_resp.get("ltp") or 0) if spot_resp.get("success") else 0.0
        chg_p = float(spot_resp.get("change_percent") or 0) if spot_resp.get("success") else 0.0
        if ltp <= 0:
            ltp = float(stale.get("ltp") or 0)
            chg_p = float(stale.get("change_pct") or 0)
        if ltp <= 0:
            return stale if stale else {}

        if light:
            # Infer soft context from day change only (no second history call)
            above = chg_p >= 0
            data = {
                "ltp": ltp,
                "change_pct": chg_p,
                "vwap": ltp,
                "ema20": ltp * (0.998 if above else 1.002),
                "vwap_dev_pct": 0.0,
                "above_ema20": above,
                "candles_5min": stale.get("candles_5min") or [],
                "light": True,
            }
            self._ul_cache[symbol] = (data, now)
            return data

        candles: List[Any] = []
        try:
            hist = self.market_service.get_historical_data(
                symbol=symbol, resolution="5", days=1,
            )
            candles = hist.get("candles") or []
        except Exception as exc:
            logger.debug("5m history failed for %s: %s", symbol, exc)
        if not candles:
            candles = stale.get("candles_5min") or []
        closes = [c["close"] for c in candles if c.get("close")]
        vwap = compute_vwap(candles) or ltp
        ema20 = compute_ema(closes, 20) or ltp
        vwap_dev = ((ltp - vwap) / vwap * 100) if vwap else 0

        data = {
            "ltp": ltp,
            "change_pct": chg_p,
            "vwap": vwap,
            "ema20": ema20,
            "vwap_dev_pct": round(vwap_dev, 3),
            "above_ema20": ltp > ema20,
            "candles_5min": candles[-60:],
            "light": False,
        }
        self._ul_cache[symbol] = (data, now)
        return data

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

    # ── Process option chain → best single strike (v3 multi-layer) ─

    def _process_option_chain(
        self,
        symbol: str,
        underlying: Dict[str, Any],
        strike_count: int = 10,
        *,
        fetch_vol_history: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        v3 pipeline:
          chain → CE/PE classify → hard filters → vol spike → Greek quality
          → underlying context → grade A+/A/B/C → optional Alert Box flags

        Returns best composite contract or None.
        """
        chain_resp = self.market_service.get_option_chain(symbol, strike_count)
        if not chain_resp.get("success"):
            return None

        chain = chain_resp.get("chain", [])
        spot = chain_resp.get("spot_price") or underlying.get("ltp", 0)
        expiries = chain_resp.get("expiries", [])

        if expiries:
            first_exp = expiries[0]
            nearest_expiry = (
                first_exp.get("expiry") or first_exp.get("date") or "N/A"
                if isinstance(first_exp, dict) else str(first_exp)
            )
        else:
            nearest_expiry = "N/A"

        ul_chg_pct = float(underlying.get("change_pct") or 0)
        vwap_dev = float(underlying.get("vwap_dev_pct") or 0)
        above_ema = bool(underlying.get("above_ema20", False))
        sym_name = _sym_name(symbol)

        # Peer volumes for chain-relative spike (fast, no API)
        peer_vols_ce: List[float] = []
        peer_vols_pe: List[float] = []
        for row in chain:
            st = row.get("strike_price")
            if not st or not spot:
                continue
            if abs(st - spot) / spot * 100 > MAX_ATM_DISTANCE_PCT:
                continue
            if row.get("call") and (row["call"].get("volume") or 0) > 0:
                peer_vols_ce.append(float(row["call"]["volume"]))
            if row.get("put") and (row["put"].get("volume") or 0) > 0:
                peer_vols_pe.append(float(row["put"]["volume"]))

        candidates: List[Dict[str, Any]] = []
        for row in chain:
            strike = row.get("strike_price")
            if not strike or strike <= 0:
                continue
            atm_dist_pct = abs(strike - spot) / spot * 100 if spot else 999
            if atm_dist_pct > MAX_ATM_DISTANCE_PCT:
                continue

            for opt_type, key in [("CE", "call"), ("PE", "put")]:
                opt = row.get(key)
                if not opt:
                    continue
                oi_change_pct = float(opt.get("oi_change_pct") or 0)
                ltp_chg_pct = float(opt.get("chg_pct") or 0)
                oi = float(opt.get("oi") or 0)
                volume = float(opt.get("volume") or 0)
                ltp = float(opt.get("ltp") or 0)
                iv = float(opt.get("iv") or 0)

                if oi <= 0 or volume <= 0:
                    continue
                if abs(oi_change_pct) < MIN_OI_CHANGE_PCT:
                    continue
                if volume < MIN_OPTION_VOLUME:
                    continue

                prelim_sig = classify_signal(
                    oi_change_pct, ltp_chg_pct, ul_chg_pct, opt_type=opt_type
                )
                if prelim_sig.get("signal") == "NEUTRAL":
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
                    "prelim_signal": prelim_sig,
                })

        if not candidates:
            return None

        def prelim_score(c: Dict) -> float:
            atm_boost = max(0.0, 1.0 - (c["atm_dist_pct"] / MAX_ATM_DISTANCE_PCT))
            return abs(c["oi_change_pct"]) * math.log(c["volume"] + 1) * (1.0 + atm_boost)

        candidates.sort(key=prelim_score, reverse=True)
        # Score top 4 only — balance quality vs API budget for 3d vol
        top_candidates = candidates[:4]
        scored: List[Dict[str, Any]] = []

        for cand in top_candidates:
            opt = cand["opt"]
            opt_sym = opt.get("symbol") or ""
            peers = peer_vols_ce if cand["opt_type"] == "CE" else peer_vols_pe
            chain_spike = chain_relative_vol_spike(cand["volume"], peers)

            vol_3day_avg = 0.0
            vol_spike_ratio = chain_spike
            vol_src = "chain_median"

            # Prefer cached / real 3-day history when available
            if fetch_vol_history and opt_sym:
                cached = self._vol_cache.get(opt_sym)
                now = datetime.now()
                need_fetch = True
                if cached:
                    vol_3day_avg, fetched_at = cached
                    if (now - fetched_at).total_seconds() < self._VOL_CACHE_TTL:
                        need_fetch = False
                # Only hit API for top-2 prelims to keep scan smooth
                if need_fetch and len(scored) < 2:
                    vol_3day_avg = self._get_3day_vol_avg(opt_sym)
                elif not need_fetch:
                    pass
                if vol_3day_avg > 0:
                    hist_spike = cand["volume"] / vol_3day_avg
                    # Use stronger of history vs chain-relative (real unusualness)
                    if hist_spike >= chain_spike:
                        vol_spike_ratio = hist_spike
                        vol_src = "3day_hist"
                    else:
                        vol_spike_ratio = max(chain_spike, hist_spike)
                        vol_src = "hybrid"

            # Hard volume filter when we have a real baseline
            if vol_src in ("3day_hist", "hybrid") and vol_3day_avg > 0:
                if vol_spike_ratio < MIN_VOL_SPIKE:
                    continue
            elif vol_src == "chain_median":
                if vol_spike_ratio < MIN_VOL_SPIKE and cand["volume"] < MIN_OPTION_VOLUME * 3:
                    continue

            signal = cand.get("prelim_signal") or classify_signal(
                cand["oi_change_pct"],
                cand["ltp_chg_pct"],
                ul_chg_pct,
                opt_type=cand["opt_type"],
            )
            direction = signal.get("direction") or "NEUTRAL"
            cluster = count_cluster_hits(
                candidates, cand["strike"], cand["opt_type"], direction
            )

            row = build_scored_contract(
                symbol=symbol,
                name=sym_name,
                nearest_expiry=nearest_expiry,
                cand=cand,
                signal=signal,
                vol_3day_avg=vol_3day_avg,
                vol_spike_ratio=vol_spike_ratio,
                vol_spike_source=vol_src,
                spot=float(spot or 0),
                ul_chg_pct=ul_chg_pct,
                vwap_dev=vwap_dev,
                above_ema=above_ema,
                cluster_hits=cluster,
            )
            if row:
                scored.append(row)

        if not scored:
            try:
                get_idea_book().ingest_neutral(symbol, float(spot or 0))
            except Exception:
                pass
            return None

        # Best by composite (LIS + greek + unusual), then grade, then LIS
        _g = {"A+": 4, "A": 3, "B": 2, "C": 1}
        scored.sort(
            key=lambda x: (
                float(x.get("composite_score") or 0),
                _g.get(x.get("grade") or "C", 0),
                float(x.get("lis") or 0),
                -float(x.get("atm_dist_pct") or 99),
            ),
            reverse=True,
        )
        best = scored[0]
        opposing = False
        if len(scored) >= 2:
            d0 = (scored[0].get("direction") or "").upper()
            d1 = (scored[1].get("direction") or "").upper()
            if (
                d0 in ("BULLISH", "BEARISH")
                and d1 in ("BULLISH", "BEARISH")
                and d0 != d1
                and float(scored[1].get("lis") or 0) >= 45
            ):
                opposing = True

        # Real VWAP / OR / 5m for any symbol that produced fuel
        if underlying.get("light"):
            rich = self._get_underlying_data(symbol, light=False)
            if rich:
                underlying = rich
                best["vwap_dev_pct"] = rich.get("vwap_dev_pct", best.get("vwap_dev_pct"))
                best["above_ema20"] = rich.get("above_ema20", best.get("above_ema20"))
                best["spot"] = rich.get("ltp") or best.get("spot")

        return self._attach_process_trade(
            symbol,
            best,
            chain=chain,
            underlying=underlying,
            opposing=opposing,
        )

    def _attach_process_trade(
        self,
        symbol: str,
        row: Dict[str, Any],
        *,
        chain: Optional[List[Dict[str, Any]]] = None,
        underlying: Optional[Dict[str, Any]] = None,
        opposing: bool = False,
        fetch_day: bool = True,
        fetch_futures: bool = True,
    ) -> Dict[str, Any]:
        """Institutional map + persistence lock. Headline unit becomes the idea."""
        underlying = underlying or {}
        spot = float(row.get("spot") or underlying.get("ltp") or 0)
        candles = underlying.get("candles_5min") or []
        try:
            levels_svc = get_levels_service()
            full = levels_svc.build_full_map(
                symbol,
                spot,
                chain=chain,
                candles_5m=candles,
                fetch_day=fetch_day,
                fetch_futures=fetch_futures,
            )
            try:
                full["mtf"] = get_mtf_service().evaluate(symbol)
            except Exception as mtf_exc:
                logger.debug("MTF evaluate failed %s: %s", symbol, mtf_exc)
                full["mtf"] = {}
            full["chain"] = chain or []
            book = get_idea_book()
            snap = snapshot_from_contract(row, opposing=opposing)
            result = book.ingest(snap, full, candles_5m=candles)
            row = book.attach_to_contract(symbol, row)
            loc = (result.get("eval") or {}).get("location") or {}
            row["location_score"] = loc.get("score")
            row["location_tags"] = loc.get("tags") or []
            row["process_composite"] = (result.get("eval") or {}).get("composite")
            row["process_recipe"] = ((result.get("eval") or {}).get("recipe") or {}).get("id")
            row["levels_map"] = {
                "day": full.get("day"),
                "session": full.get("session"),
                "structure": full.get("structure"),
                "futures": full.get("futures"),
                "zones": full.get("zones"),
                "pivot_side": full.get("pivot_side"),
                "camarilla_regime": full.get("camarilla_regime"),
                "atr": full.get("atr"),
                "mtf": full.get("mtf"),
                "execution": (result.get("eval") or {}).get("execution"),
            }
            row["idea_transition"] = result.get("transition")
        except Exception as exc:
            logger.warning("process-trade attach failed for %s: %s", symbol, exc)
        return row

    def get_process_board(self, limit: int = 8) -> Dict[str, Any]:
        board = get_idea_book().board(limit=limit)
        return {
            "success": True,
            "engine": "v4-process",
            **board,
            "timestamp": datetime.now().isoformat(),
        }

    def get_symbol_idea(self, symbol: str) -> Dict[str, Any]:
        idea = get_idea_book().get(symbol)
        day = get_levels_service().peek_day_map(symbol)
        return {
            "success": True,
            "symbol": symbol,
            "idea": idea,
            "day_map": day,
            "timestamp": datetime.now().isoformat(),
        }

    # ── Public: Full scan (180 stocks, 1 per stock) ───────────────

    def scan_all(
        self,
        symbols: Optional[List[str]] = None,
        min_lis: float = 0,
        opt_type_filter: Optional[str] = None,
        strike_count: int = 12,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Scan FNO universe — ONE best strike per stock (v3 graded).

        Returns:
          flagged     → Grade A / A+ (main Normal Radar, actionable)
          watch       → Grade B (watch only)
          alert_box   → Unusual / big-player (sorted by unusual_score)
          all_hits    → every non-C row for logs

        progress_callback(scanned, total, current_symbol, flagged_row|None, error|None)
        """
        if not self._is_authenticated():
            return {
                "success": False,
                "error": "Not authenticated with Fyers API",
                "flagged": [],
                "watch": [],
                "alert_box": [],
            }

        self._scan_running = True
        watch = filter_valid_symbols(symbols or ALL_FNO_WATCHLIST)
        total = len(watch)
        all_hits: List[Dict] = []
        errors: List[str] = []
        scanned = 0
        rate_limited_skips = 0
        aborted_rate_limit = False
        BATCH_SIZE = 12
        BATCH_SLEEP = 0.35

        def _progress(sym: str, flagged_row=None, err=None):
            if progress_callback:
                try:
                    progress_callback(scanned, total, sym, flagged_row, err)
                except Exception:
                    pass

        try:
            for batch_start in range(0, len(watch), BATCH_SIZE):
                batch = watch[batch_start: batch_start + BATCH_SIZE]
                for sym in batch:
                    if not is_valid_symbol(sym):
                        scanned += 1
                        _progress(sym, err="invalid_symbol")
                        continue
                    try:
                        # Light underlying on bulk scan — real spot, soft context
                        underlying = self._get_underlying_data(sym, light=True)
                        if not underlying:
                            scanned += 1
                            _progress(sym, err="no_underlying")
                            continue

                        best = self._process_option_chain(
                            sym, underlying, strike_count, fetch_vol_history=True
                        )
                        if best is None:
                            scanned += 1
                            _progress(sym)
                            continue

                        if opt_type_filter and best["type"] != opt_type_filter:
                            scanned += 1
                            _progress(sym)
                            continue
                        if min_lis > 0 and best["lis"] < min_lis:
                            scanned += 1
                            _progress(sym)
                            continue

                        all_hits.append(best)
                        scanned += 1
                        # Stream A/A+ to job progress UI immediately
                        if best.get("actionable") or best.get("alert_box"):
                            _progress(sym, flagged_row=best)
                        else:
                            _progress(sym)

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

                if batch_start + BATCH_SIZE < len(watch):
                    try:
                        from app.services.rate_limiter import get_fyers_limiter
                        lim = get_fyers_limiter()
                        if lim.in_cooldown:
                            time.sleep(min(lim.cooldown_remaining, 30))
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
        finally:
            self._scan_running = False

        # Partition per v3 product rules
        radar = [h for h in all_hits if h.get("grade") in ("A", "A+")]
        watch_list = [h for h in all_hits if h.get("grade") == "B"]
        alert_box = [h for h in all_hits if h.get("alert_box")]

        radar.sort(
            key=lambda x: (
                1 if x.get("grade") == "A+" else 0,
                float(x.get("composite_score") or 0),
                float(x.get("lis") or 0),
            ),
            reverse=True,
        )
        watch_list.sort(key=lambda x: float(x.get("composite_score") or 0), reverse=True)
        alert_box.sort(key=lambda x: float(x.get("unusual_score") or 0), reverse=True)
        all_hits.sort(key=lambda x: float(x.get("composite_score") or 0), reverse=True)

        # flagged = actionable main radar (backward compatible primary list)
        # include watch when user wants full board — keep flagged = A/A+ only for quality
        flagged = list(radar)

        board = get_idea_book().board(limit=8)
        result = {
            "success": True,
            "engine": "v5-mtf",
            "scanned": scanned,
            "universe_requested": total,
            "total_flagged": len(flagged),
            "flagged": flagged,
            "watch": watch_list,
            "alert_box": alert_box,
            "all_hits": all_hits,
            "ideas": board.get("active") or [],
            "ideas_confirmed": board.get("confirmed") or [],
            "ideas_pullbacks": board.get("pullbacks") or [],
            "ideas_watch": board.get("watch") or [],
            "ideas_conflict": board.get("conflict") or [],
            "idea_counts": board.get("counts") or {},
            "grade_counts": {
                "A+": sum(1 for h in all_hits if h.get("grade") == "A+"),
                "A": sum(1 for h in all_hits if h.get("grade") == "A"),
                "B": sum(1 for h in all_hits if h.get("grade") == "B"),
                "C": sum(1 for h in all_hits if h.get("grade") == "C"),
            },
            "errors": errors,
            "rate_limited_skips": rate_limited_skips,
            "partial": aborted_rate_limit or scanned < total,
            "completion_pct": round(100.0 * min(scanned, total) / max(total, 1), 1),
            "timestamp": datetime.now().isoformat(),
            "market_hours": self._is_market_hours(),
            "rules": {
                "max_atm_pct": MAX_ATM_DISTANCE_PCT,
                "min_vol_spike": MIN_VOL_SPIKE,
                "min_oi_change_pct": MIN_OI_CHANGE_PCT,
                "min_volume": MIN_OPTION_VOLUME,
                "description": (
                    "v4 process: CE/PE matrix → institutional levels (pivot/CPR/"
                    "Camarilla/OI walls/VWAP) → persistence + hysteresis lock. "
                    "Headline is the Active Idea, not the last snapshot."
                ),
            },
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
            underlying = self._get_underlying_data(symbol, light=False)
            if not underlying:
                underlying = self._get_underlying_data(symbol, light=True)

            chain_resp: Dict[str, Any] = {}
            try:
                chain_resp = self.market_service.get_option_chain(symbol, strike_count)
            except Exception as exc:
                logger.debug("option chain failed for %s: %s", symbol, exc)
                chain_resp = {}

            spot = chain_resp.get("spot_price") or (underlying or {}).get("ltp") or 0
            if (not underlying or not underlying.get("ltp")) and spot:
                underlying = {
                    **(underlying or {}),
                    "ltp": spot,
                    "change_pct": (underlying or {}).get("change_pct") or 0,
                    "vwap": spot,
                    "ema20": spot,
                    "vwap_dev_pct": 0.0,
                    "above_ema20": True,
                    "candles_5min": (underlying or {}).get("candles_5min") or [],
                    "light": True,
                }

            if not underlying or not underlying.get("ltp"):
                idea = get_idea_book().get(symbol)
                last = self.get_last_scan() or {}
                row = next(
                    (
                        r
                        for r in (last.get("flagged") or [])
                        + (last.get("watch") or [])
                        + (last.get("ideas") or [])
                        if r.get("symbol") == symbol
                    ),
                    None,
                )
                if idea or row:
                    px = float((idea or {}).get("spot") or (row or {}).get("spot") or 0)
                    return {
                        "success": True,
                        "symbol": symbol,
                        "name": _sym_name(symbol),
                        "underlying": {
                            "ltp": px,
                            "change_pct": 0,
                            "vwap": px,
                            "ema20": px,
                            "vwap_dev_pct": 0,
                            "above_ema20": True,
                            "candles_5min": [],
                            "light": True,
                        },
                        "chain": [],
                        "spot_price": px,
                        "pcr": None,
                        "india_vix": None,
                        "atm_strike": None,
                        "expiries": [],
                        "flagged_contracts": [row] if row and row.get("strike") else [],
                        "candles_5min": [],
                        "idea": idea,
                        "levels": (row or {}).get("levels_map") if row else None,
                        "partial": True,
                        "warning": "Live quote unavailable — showing last process idea",
                        "timestamp": datetime.now().isoformat(),
                    }
                return {"success": False, "error": f"Failed to get data for {symbol}", "flagged": []}
            expiries = chain_resp.get("expiries", [])

            normalized_expiries = [
                e.get("expiry") or e.get("date") or str(e) if isinstance(e, dict) else str(e)
                for e in expiries
            ]

            # Get best contract (reuse _process_option_chain)
            best = None
            try:
                best = self._process_option_chain(symbol, underlying, strike_count)
            except Exception as exc:
                logger.warning("process attach in flow failed for %s: %s", symbol, exc)
            flagged = [best] if best else []
            idea = get_idea_book().get(symbol)
            levels_map = (best or {}).get("levels_map")
            if levels_map is None:
                try:
                    levels_map = get_levels_service().build_full_map(
                        symbol,
                        float(spot or underlying.get("ltp") or 0),
                        chain=chain_resp.get("chain") or [],
                        candles_5m=underlying.get("candles_5min") or [],
                    )
                except Exception:
                    levels_map = None

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
                "idea": idea,
                "levels": levels_map,
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
