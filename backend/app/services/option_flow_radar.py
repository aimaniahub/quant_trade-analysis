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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
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
        self._scan_heartbeat = 0.0

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
            slim = dict(self._last_scan)
            slim.pop("all_hits", None)
            rc.set_json(
                rc.key("radar", "last_scan"),
                {
                    "scan": slim,
                    "at": self._last_scan_at.isoformat(),
                },
                ttl=14400,
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
        fetch_vol_history: bool = False,
        enrich_underlying: bool = True,
        attach_heavy: bool = True,
        chain_resp: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        v3 pipeline:
          chain → CE/PE classify → hard filters → vol spike → Greek quality
          → underlying context → grade A+/A/B/C → optional Alert Box flags

        Returns best composite contract or None.
        """
        if chain_resp is None:
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

        if enrich_underlying and underlying.get("light"):
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
            fetch_day=attach_heavy,
            fetch_futures=attach_heavy,
            skip_mtf=not attach_heavy,
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
        skip_mtf: bool = False,
    ) -> Dict[str, Any]:
        """Institutional map + persistence lock. Headline unit becomes the idea."""
        underlying = underlying or {}
        spot = float(row.get("spot") or underlying.get("ltp") or 0)
        candles = list(underlying.get("candles_5min") or [])
        try:
            from app.services import symbol_store as store

            if len(candles) < 4:
                m15 = store.get_history(symbol, "15", min_bars=8) or []
                if m15:
                    candles = m15
            levels_svc = get_levels_service()
            # Day map is store-first. Futures Fyers only when fetch_futures=True
            # (detail path). Harvest peeks stored futures instead.
            full = levels_svc.build_full_map(
                symbol,
                spot,
                chain=chain,
                candles_5m=candles,
                fetch_day=True,
                fetch_futures=fetch_futures,
            )
            if not (full.get("futures") or {}).get("ok"):
                stored_fut = (store.get(symbol) or {}).get("futures") or {}
                if stored_fut:
                    full["futures"] = stored_fut
            full["mtf"] = {}
            try:
                # Store-only 4H/1H/15m — never a Fyers walk.
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

    def _harvest_quotes_pass(self, symbols: List[str]) -> None:
        """Pass A — batched quotes (≤50) into the symbol store."""
        from app.services import symbol_store as store
        from app.services.fno_stocks import filter_valid_symbols

        universe = filter_valid_symbols(list(dict.fromkeys([
            *symbols,
            *FNO_INDICES,
            "NSE:INDIAVIX-INDEX",
        ])))
        logger.info("harvest quotes pass n=%s", len(universe))
        for i in range(0, len(universe), 50):
            chunk = universe[i: i + 50]
            try:
                self.market_service.get_quotes(chunk)
            except Exception as exc:
                logger.warning("harvest quotes chunk %s: %s", i, exc)

    def _underlying_from_store(self, symbol: str) -> Dict[str, Any]:
        """Spot from the harvest quotes pass — no extra Fyers call."""
        from app.services import symbol_store as store

        snap = store.get(symbol) or {}
        spot = snap.get("spot") or {}
        ltp = float(spot.get("ltp") or 0)
        if ltp <= 0:
            return {}
        chg = float(spot.get("change_percent") or spot.get("chp") or 0)
        return {
            "ltp": ltp,
            "change_pct": chg,
            "vwap": ltp,
            "ema20": ltp,
            "vwap_dev_pct": 0.0,
            "above_ema20": chg >= 0,
            "candles_5min": [],
            "light": True,
        }

    def _maybe_harvest_history(self, symbol: str) -> None:
        """Pass C — 15m/40d and D/30d when stale. Derive 60/240 in process."""
        from app.services import symbol_store as store
        from app.services.rate_limiter import get_fyers_limiter

        if get_fyers_limiter().in_cooldown:
            return

        if not store.is_fresh(symbol, "history.15", store.history_15_ttl()):
            days = store.harvest_history_15_days()
            hist = self.market_service.get_historical_data(
                symbol, resolution="15", days=days
            )
            candles = hist.get("candles") or []
            if hist.get("success") and candles:
                store.put_history(symbol, "15", candles, days)
                self._write_derived(symbol, candles_15=candles)

        if not store.is_fresh(symbol, "history.D"):
            days_d = store.harvest_history_d_days()
            daily = self.market_service.get_historical_data(
                symbol, resolution="D", days=days_d
            )
            d_bars = daily.get("candles") or []
            if daily.get("success") and d_bars:
                store.put_history(symbol, "D", d_bars, days_d)
                snap = store.get(symbol) or {}
                h = ((snap.get("history") or {}).get("D") or {})
                h["ist_date"] = datetime.now().strftime("%Y-%m-%d")
                store.put(symbol, {"history": {"D": h}})

    def _write_derived(
        self,
        symbol: str,
        candles_15: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """CPU-only derived fields (7/200, rel-vol, VWAP, MTF) on the snapshot."""
        from app.services import symbol_store as store

        bars = candles_15 or store.get_history(symbol, "15", min_bars=20) or []
        dailies = store.get_history(symbol, "D", min_bars=10) or []
        derived: Dict[str, Any] = {}
        if bars:
            closes = [float(c.get("close") or 0) for c in bars if c.get("close")]
            ema20 = compute_ema(closes, 20)
            try:
                from app.services.levels import build_session_map

                sess = build_session_map(bars, closes[-1] if closes else 0)
                vwap = sess.get("vwap")
                derived["vwap_side"] = sess.get("vwap_side")
            except Exception:
                vwap = compute_vwap(bars[-30:]) if len(bars) >= 2 else None
            vols = [float(c.get("volume") or 0) for c in bars]
            cur = vols[-1] if vols else 0.0
            prev = vols[-21:-1] if len(vols) > 21 else vols[:-1]
            avg = (sum(prev) / len(prev)) if prev else 0.0
            rel = (cur / avg) if avg else 0.0
            derived["vwap"] = round(vwap, 2) if vwap else None
            derived["ema20_15"] = round(ema20, 2) if ema20 else None
            derived["rel_vol_15"] = round(rel, 2)
            try:
                from app.services.strategies.ma7200_scanner import detect_7_200_cross

                cross = detect_7_200_cross(bars, require_volume=True, skip_session_edge=True)
                if cross:
                    derived["ma7200"] = {
                        "cross": cross.get("cross_type"),
                        "bars_ago": cross.get("bars_ago"),
                        "fast": cross.get("ema7"),
                        "slow": cross.get("ema200"),
                    }
                else:
                    derived["ma7200"] = {"cross": None, "bars_ago": None}
            except Exception:
                pass
        if dailies or bars:
            try:
                h4 = store.aggregate_ohlcv(bars, 240) if bars else []
                h1 = store.aggregate_ohlcv(bars, 60) if bars else []
                packed = get_mtf_service().evaluate(
                    symbol,
                    daily_candles=dailies,
                    m15_candles=bars,
                    h4_candles=h4,
                    h1_candles=h1,
                )
                derived["mtf"] = {
                    "daily_bias": packed.get("daily_bias") or packed.get("daily"),
                    "h4_bias": packed.get("h4_bias") or packed.get("h4"),
                    "h1_bias": packed.get("h1_bias") or packed.get("h1"),
                    "m15_bias": packed.get("m15_bias") or packed.get("m15"),
                }
            except Exception as exc:
                logger.debug("derived mtf %s: %s", symbol, exc)
        if derived:
            store.put_derived(symbol, derived)

    def _rebuild_hv_index(self) -> None:
        """Write optiongreek:idx:hv from stored 15m so Quant reads Redis."""
        try:
            from app.services.high_volume_scanner import get_scanner_service
            from app.services import symbol_store as store

            svc = get_scanner_service()
            result = svc.scan_from_store(timeframe="15", top_count=8)
            if result.get("success"):
                store.set_hv_index(result)
        except Exception as exc:
            logger.debug("rebuild hv index: %s", exc)

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
        strike_count: int = 14,
        progress_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Harvest + scan FNO universe — ONE best strike per stock (v3 graded).

        This is the only universe Fyers writer. After each symbol the Redis
        snapshot is upserted so VAT / 7/200 / HV / home read the same book.

        Returns:
          flagged     → Grade A / A+ (main Normal Radar, actionable)
          watch       → Grade B (watch only)
          alert_box   → Unusual / big-player (sorted by unusual_score)
          all_hits    → every non-C row for logs

        progress_callback(scanned, total, current_symbol, flagged_row|None, error|None)
        """
        from app.services import symbol_store as store

        if not self._is_authenticated():
            return {
                "success": False,
                "error": "Not authenticated with Fyers API",
                "flagged": [],
                "watch": [],
                "alert_box": [],
            }
        if self._scan_running:
            stuck_for = time.time() - float(getattr(self, "_scan_heartbeat", 0) or 0)
            if stuck_for < 90:
                return {
                    "success": False,
                    "error": "Scan already running",
                    "flagged": [],
                    "watch": [],
                    "alert_box": [],
                }
            logger.warning("Radar stealing stuck scan lock (idle %.0fs)", stuck_for)

        self._scan_running = True
        self._scan_heartbeat = time.time()
        watch = filter_valid_symbols(symbols or ALL_FNO_WATCHLIST)
        try:
            prev_fail = list((store.get_harvest_meta() or {}).get("failed_remaining") or [])
            if prev_fail:
                head = [s for s in prev_fail if s in watch]
                tail = [s for s in watch if s not in head]
                watch = head + tail
                logger.info("Radar prioritizing %s previously missed chains", len(head))
        except Exception:
            pass
        total = len(watch)
        all_hits: List[Dict] = []
        errors: List[str] = []
        scanned = 0
        rate_limited_skips = 0
        SYMBOL_TIMEOUT_SEC = 25.0
        BATCH_SIZE = 12
        BATCH_SLEEP = 0.2
        CHAIN_WAIT_ATTEMPTS = 6
        pass_id = f"h{int(time.time())}"
        _hw = store.harvest_writer()
        _hw.__enter__()
        store.set_harvest_meta({
            "running": True,
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "scanned": 0,
            "total": total,
            "current": None,
            "pass_id": pass_id,
            "phase": "quotes",
        })
        try:
            self._harvest_quotes_pass(watch)
        except Exception as exc:
            logger.warning("harvest quotes pass failed: %s", exc)

        def _progress(sym: str, flagged_row=None, err=None, *, status: str = "ok", ms: int = 0):
            if progress_callback:
                try:
                    progress_callback(scanned, total, sym, flagged_row, err, status, ms)
                except TypeError:
                    try:
                        progress_callback(scanned, total, sym, flagged_row, err)
                    except Exception:
                        pass
                except Exception:
                    pass

        def _scan_one(
            sym: str,
            *,
            chain_only: bool = False,
            force_chain: bool = False,
        ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
            if not is_valid_symbol(sym):
                return None, "invalid_symbol"
            underlying = self._underlying_from_store(sym)
            if not underlying and not chain_only:
                underlying = self._get_underlying_data(sym, light=True)
            chain_resp = self.market_service.get_option_chain(
                sym, strike_count, force_refresh=force_chain
            )
            if not chain_resp or not chain_resp.get("success"):
                why = (chain_resp or {}).get("error") or "no_chain"
                return None, f"no_chain:{why}"[:120]
            if len(chain_resp.get("chain") or []) < 2:
                return None, "no_chain:empty"
            spot = float(chain_resp.get("spot_price") or (underlying or {}).get("ltp") or 0)
            if not underlying or not float((underlying or {}).get("ltp") or 0):
                if spot <= 0:
                    return None, "no_underlying"
                underlying = {
                    "ltp": spot,
                    "change_pct": 0.0,
                    "vwap": spot,
                    "ema20": spot,
                    "vwap_dev_pct": 0.0,
                    "above_ema20": True,
                    "candles_5min": [],
                    "light": True,
                }
            # Fast path: chain + LIS only. No 3-day hist, no 5m, no MTF.
            best = self._process_option_chain(
                sym,
                underlying,
                strike_count,
                fetch_vol_history=False,
                enrich_underlying=False,
                attach_heavy=False,
                chain_resp=chain_resp,
            )
            if best is None:
                return None, None
            if opt_type_filter and best.get("type") != opt_type_filter:
                return None, None
            if min_lis > 0 and float(best.get("lis") or 0) < min_lis:
                return None, None
            return best, None

        def _retryable(err: Optional[str]) -> bool:
            if not err:
                return False
            e = str(err).lower()
            if e == "invalid_symbol" or e.startswith("invalid_symbol"):
                return False
            return True

        def _quota_err(err: Optional[str]) -> bool:
            if not err:
                return False
            e = str(err).lower()
            if e in ("invalid_symbol", "no_chain:empty", "no_underlying"):
                return False
            try:
                from app.services.rate_limiter import is_rate_limit_error
                if is_rate_limit_error(e):
                    return True
            except Exception:
                pass
            return e == "timeout" or e.startswith("no_chain:")

        def _weight_hit(hit: Dict[str, Any]) -> Dict[str, Any]:
            try:
                from app.services.strategies.rsi_desk import weight_radar_row

                return weight_radar_row(hit)
            except Exception as wexc:
                logger.debug("desk weight %s: %s", hit.get("symbol"), wexc)
                return hit

        logger.info("Radar harvest start n=%s strike_count=%s pass=%s", total, strike_count, pass_id)
        store.set_harvest_meta({"phase": "chains", "running": True, "total": total})
        workers = {"pool": ThreadPoolExecutor(max_workers=1, thread_name_prefix="radar-sym")}
        failed_syms: List[str] = []
        retry_attempted = 0
        retry_recovered = 0

        def _reset_pool() -> None:
            try:
                workers["pool"].shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            workers["pool"] = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radar-sym")

        def _run_one(
            sym: str,
            timeout: float,
            *,
            chain_only: bool = False,
            force_chain: bool = False,
        ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
            nonlocal rate_limited_skips
            try:
                fut = workers["pool"].submit(
                    _scan_one, sym, chain_only=chain_only, force_chain=force_chain
                )
                return fut.result(timeout=timeout)
            except FuturesTimeout:
                logger.warning("Radar skip %s — exceeded %.0fs", sym, timeout)
                _reset_pool()
                return None, "timeout"
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
                logger.warning("Radar scan error for %s: %s", sym, exc)
                return None, msg[:120]

        def _cooldown_if_needed(cap: float = 120.0) -> None:
            try:
                from app.services.rate_limiter import get_fyers_limiter
                lim = get_fyers_limiter()
                if lim.in_cooldown:
                    wait = min(max(lim.cooldown_remaining, 0.5), cap)
                    logger.info("Radar cooldown %.0fs — staying on this name", wait)
                    _sleep_hb(wait)
            except Exception:
                pass

        def _sleep_hb(seconds: float) -> None:
            end = time.time() + max(0.0, seconds)
            while time.time() < end:
                self._scan_heartbeat = time.time()
                time.sleep(min(5.0, max(0.05, end - time.time())))

        def _fetch_chain_wait(sym: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
            """Do not walk past this symbol on quota. Wait, then fetch again."""
            nonlocal retry_attempted, retry_recovered
            last_err = None
            for attempt in range(CHAIN_WAIT_ATTEMPTS):
                _cooldown_if_needed(120.0)
                self._scan_heartbeat = time.time()
                force = attempt > 0
                hit, err = _run_one(
                    sym,
                    SYMBOL_TIMEOUT_SEC,
                    chain_only=True,
                    force_chain=force,
                )
                if not err:
                    if attempt > 0:
                        retry_recovered += 1
                    return hit, None
                last_err = err
                if not _quota_err(err):
                    return hit, err
                retry_attempted += 1
                try:
                    from app.services.rate_limiter import get_fyers_limiter
                    lim = get_fyers_limiter()
                    if not lim.in_cooldown:
                        lim.trip_limit(f"harvest {sym}: {err}")
                    wait = min(max(lim.cooldown_remaining, 4.0), 45.0)
                except Exception:
                    wait = 8.0
                _progress(sym, err=err, status="wait", ms=int(wait * 1000))
                logger.info("Radar WAIT %s attempt %s/%s %s — sleep %.0fs", sym, attempt + 1, CHAIN_WAIT_ATTEMPTS, err, wait)
                _sleep_hb(wait)
            return None, last_err

        try:
            for batch_start in range(0, len(watch), BATCH_SIZE):
                batch = watch[batch_start: batch_start + BATCH_SIZE]
                for sym in batch:
                    t0 = time.perf_counter()
                    self._scan_heartbeat = time.time()
                    _progress(sym, status="start")
                    hit, err = _fetch_chain_wait(sym)

                    ms = int((time.perf_counter() - t0) * 1000)
                    scanned += 1
                    if hit:
                        hit = _weight_hit(hit)
                        all_hits.append(hit)
                        _progress(sym, flagged_row=hit, status="hit", ms=ms)
                        logger.info("Radar HIT %s %s%s lis=%.0f %dms", sym, hit.get("strike"), hit.get("type"), float(hit.get("lis") or 0), ms)
                    elif err:
                        errors.append(f"{sym}: {err}")
                        if _retryable(err):
                            failed_syms.append(sym)
                        _progress(sym, err=err, status="err", ms=ms)
                        logger.info("Radar %s %s %dms", err, sym, ms)
                    else:
                        _progress(sym, status="skip", ms=ms)

                    store.set_harvest_meta({
                        "scanned": scanned,
                        "current": sym,
                        "phase": "chains",
                    })

                if batch_start + BATCH_SIZE < len(watch):
                    _cooldown_if_needed(120.0)
                    time.sleep(BATCH_SLEEP)

            # History only after every name has had a real chance at a chain.
            store.set_harvest_meta({"phase": "history", "running": True})
            try:
                from app.services.rate_limiter import get_fyers_limiter
                for sym in watch:
                    if get_fyers_limiter().in_cooldown:
                        break
                    try:
                        self._maybe_harvest_history(sym)
                    except Exception as hist_exc:
                        logger.debug("harvest history %s: %s", sym, hist_exc)
                    self._scan_heartbeat = time.time()
            except Exception:
                pass

            got = {h.get("symbol") for h in all_hits}
            failed_syms = [s for s in failed_syms if s not in got]
        except Exception:
            try:
                _hw.__exit__(None, None, None)
            except Exception:
                pass
            raise
        finally:
            try:
                workers["pool"].shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self._scan_running = False

        # Partition per v3 product rules — rank by stacked desk score
        from app.services.strategies.rsi_desk import weight_radar_rows

        all_hits = weight_radar_rows(all_hits)
        radar = [h for h in all_hits if h.get("grade") in ("A", "A+")]
        watch_list = [h for h in all_hits if h.get("grade") == "B"]
        alert_box = [h for h in all_hits if h.get("alert_box")]

        radar.sort(
            key=lambda x: (
                float(x.get("desk_score") or 0),
                1 if x.get("grade") == "A+" else 0,
                float(x.get("composite_score") or 0),
                float(x.get("lis") or 0),
            ),
            reverse=True,
        )
        watch_list.sort(
            key=lambda x: (
                float(x.get("desk_score") or 0),
                float(x.get("composite_score") or 0),
            ),
            reverse=True,
        )
        alert_box.sort(key=lambda x: float(x.get("unusual_score") or 0), reverse=True)

        # flagged = actionable main radar (backward compatible primary list)
        # include watch when user wants full board — keep flagged = A/A+ only for quality
        flagged = list(radar)

        logger.info(
            "Radar full FNO scan done scanned=%s/%s hits=%s errors=%s retry=%s/%s",
            scanned, total, len(all_hits), len(errors), retry_recovered, retry_attempted,
        )
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
            "retry_attempted": retry_attempted,
            "retry_recovered": retry_recovered,
            "failed_remaining": failed_syms,
            "ideas": board.get("active") or [],
            "ideas_confirmed": board.get("confirmed") or [],
            "ideas_bullish": board.get("bullish") or [],
            "ideas_bearish": board.get("bearish") or [],
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
            "partial": scanned < total,
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
        # Only the full FNO universe may replace the board. A TOP / subset
        # pass (scheduler) must not reshuffle filters mid-session.
        full_n = len(filter_valid_symbols(ALL_FNO_WATCHLIST))
        is_full_pass = total >= full_n and not result.get("partial")
        if is_full_pass or not self._last_scan:
            if is_full_pass or symbols is None:
                self._last_scan = result
                self._last_scan_at = datetime.now()
                self._persist_last_scan()
        try:
            from app.services.levels import get_levels_service

            flagged_syms = list(dict.fromkeys(
                [h.get("symbol") for h in flagged if h.get("symbol")]
            ))
            for fsym in flagged_syms[:40]:
                try:
                    get_levels_service().get_futures(fsym)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self._rebuild_hv_index()
        except Exception:
            pass
        try:
            store.set_harvest_meta({
                "running": False,
                "finished_at": datetime.now().isoformat(),
                "scanned": scanned,
                "total": total,
                "current": None,
                "pass_id": pass_id,
                "phase": "idle",
                "flagged": result.get("total_flagged"),
                "retry_attempted": retry_attempted,
                "retry_recovered": retry_recovered,
                "failed_remaining": failed_syms,
            })
        except Exception:
            pass
        try:
            _hw.__exit__(None, None, None)
        except Exception:
            pass
        return result

    # ── Public: Single symbol option chain with LIS ───────────────

    def get_symbol_flow(
        self,
        symbol: str,
        strike_count: int = 14,
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
            try:
                from app.services.strategies.rsi_desk import weight_radar_rows

                flagged = weight_radar_rows(flagged)
                if flagged:
                    best = flagged[0]
            except Exception:
                pass
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
