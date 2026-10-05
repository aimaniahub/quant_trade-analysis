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
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
import math
import threading
import time
import logging

from app.services.fyers_market import get_market_service
from app.services.fyers_auth import get_auth_service
from app.services.fno_stocks import (
    FNO_STOCKS,
    FNO_INDICES,
    TOP_FNO_STOCKS,
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
    derive_oi_change_pct,
    MIN_PREMIUM_CHG_PCT,
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

# Phase 2 harvest — concurrency hides RTT; limiter owns quota
CHAIN_WORKERS = 4
HARVEST_RPS = 3.0
SYMBOL_TIMEOUT_SEC = 8.0
RETRY_BACKOFF_SEC = 1.5
MAX_CHAIN_RETRIES = 0

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
        self._scan_lock = threading.Lock()
        self._live_all_hits: List[Dict[str, Any]] = []
        self._symbol_states: Dict[str, Dict[str, Any]] = {}
        self._ok_chain = 0
        self._attempted = 0
        self._skipped_syms: List[str] = []
        self._error_syms: List[str] = []
        self._harvest_symbol_telemetry: List[Dict[str, Any]] = []
        self._harvest_id: Optional[str] = None
        self._harvest_t0 = 0.0
        self._harvest_grants0 = 0
        self._harvest_trips0 = 0
        self._history_stop = threading.Event()
        self._history_thread: Optional[threading.Thread] = None
        self._board_lock = threading.Lock()
        self._skip_symbols: set = set()
        self._failed_remaining: List[str] = []
        self._last_board_persist_at = 0.0
        self._rescored_store = False
        self._hot_symbols: List[str] = []
        self._news_focus: List[Dict[str, Any]] = []

    def set_news_focus(self, symbols: List[str], picks: Optional[List[Dict[str, Any]]] = None) -> None:
        self._hot_symbols = [s for s in (symbols or []) if s]
        self._news_focus = list(picks or [])

    def get_hot_symbols(self) -> List[str]:
        return list(self._hot_symbols)

    def _is_authenticated(self) -> bool:
        return bool(self.auth_service.get_fyers_model())

    def _persist_last_scan(self) -> None:
        """Redis + memory durability for last radar board (restart-safe)."""
        if not self._last_scan or not self._last_scan_at:
            return
        slim = dict(self._last_scan)
        slim.pop("all_hits", None)
        try:
            from app.services import symbol_store as store
            store.set_board(slim)
        except Exception:
            pass
        try:
            from app.services import redis_client as rc
            if not rc.is_available():
                return
            from app.services.symbol_store import session_snapshot_ttl
            rc.set_json(
                rc.key("radar", "last_scan"),
                {
                    "scan": slim,
                    "at": self._last_scan_at.isoformat(),
                },
                ttl=session_snapshot_ttl(),
            )
        except Exception:
            pass

    def _hydrate_last_scan_from_redis(self) -> None:
        if self._last_scan:
            return
        scan = None
        at = None
        try:
            from app.services import symbol_store as store
            scan = store.get_board()
        except Exception:
            scan = None
        if not scan:
            try:
                from app.services import redis_client as rc
                if rc.is_available():
                    raw = rc.get_json(rc.key("radar", "last_scan"))
                    if isinstance(raw, dict):
                        scan = raw.get("scan")
                        at = raw.get("at")
            except Exception:
                scan = None
        if not scan:
            return
        self._last_scan = scan
        try:
            self._last_scan_at = datetime.fromisoformat(at) if at else datetime.now()
        except Exception:
            self._last_scan_at = datetime.now()

    def get_cached_scan(self, max_age_seconds: int = 900) -> Optional[Dict[str, Any]]:
        """Return last scan if fresh enough (memory, then Redis / last session)."""
        self._hydrate_last_scan_from_redis()
        last = self._last_scan
        at = self._last_scan_at
        if not last:
            try:
                from app.services import symbol_store as store
                last = store.get_session_board()
            except Exception:
                last = None
            if last:
                at = None
        if not last:
            return None
        age = None
        if at:
            age = (datetime.now() - at).total_seconds()
            if age > max_age_seconds:
                # Display path may still want last_session; callers that need
                # freshness use a large max_age. Drop only when explicitly tight.
                if max_age_seconds < 3600:
                    return None
        return self._annotate_board({**last, "cache_age_seconds": round(age, 1) if age is not None else None})

    def _annotate_board(self, board: Dict[str, Any]) -> Dict[str, Any]:
        from app.utils.market_hours import data_mode, last_session_date, market_open_time_ist, session_is_open
        out = dict(board)
        live = session_is_open()
        out["market_hours"] = live
        out["data_mode"] = data_mode()
        out["session_date"] = out.get("session_date") or last_session_date().isoformat()
        out["as_of"] = out.get("timestamp") or out.get("as_of")
        out["next_open"] = market_open_time_ist() if not live else "Market is OPEN"
        return out

    def pin_last_session(self) -> Optional[Dict[str, Any]]:
        """Freeze the current board as the after-hours last-session snapshot."""
        self._hydrate_last_scan_from_redis()
        last = self._last_scan
        if not last:
            try:
                from app.services import symbol_store as store
                last = store.get_board()
            except Exception:
                last = None
        if not last:
            return None
        pinned = self._annotate_board(dict(last))
        pinned["data_mode"] = "last_close"
        try:
            from app.services import symbol_store as store
            store.set_session_board(pinned)
        except Exception:
            pass
        return pinned

    def get_last_scan(self) -> Optional[Dict[str, Any]]:
        self._hydrate_last_scan_from_redis()
        last = self._last_scan
        if (
            last
            and not self._scan_running
            and not self._rescored_store
            and not (last.get("flagged") or last.get("flow") or last.get("watch"))
            and int(last.get("ok_chain") or 0) > 0
        ):
            self._rescored_store = True
            threading.Thread(
                target=self.rescore_from_store,
                name="radar-rescore",
                daemon=True,
            ).start()
        if not last:
            try:
                from app.services import symbol_store as store
                last = store.get_session_board() or store.get_board()
            except Exception:
                last = None
            if last:
                self._last_scan = last
        if not last:
            return None
        age = (
            (datetime.now() - self._last_scan_at).total_seconds()
            if self._last_scan_at
            else None
        )
        return self._annotate_board({**last, "cache_age_seconds": age, "scan_running": self._scan_running})

    def rescore_from_store(self) -> Dict[str, Any]:
        """Re-run LIS/process on chains already in the book — 0 Fyers calls."""
        if getattr(self, "_rescore_running", False):
            return self._last_scan or {}
        self._rescore_running = True
        try:
            return self._rescore_from_store_body()
        finally:
            self._rescore_running = False

    def _rescore_from_store_body(self) -> Dict[str, Any]:
        from app.services import symbol_store as store
        from app.services.chain_desk import evaluate
        from app.services.chain_anomaly import summarize_report

        watch = filter_valid_symbols(ALL_FNO_WATCHLIST)
        for row in (self._last_scan or {}).get("symbol_states") or []:
            sym = (row or {}).get("symbol")
            if sym and sym not in self._symbol_states:
                self._symbol_states[str(sym)] = dict(row)
        hits: List[Dict[str, Any]] = []
        for sym in watch:
            chain_resp = store.get_chain(sym, 14) or {}
            if not chain_resp.get("success") or len(chain_resp.get("chain") or []) < 2:
                continue
            try:
                report = evaluate(
                    sym,
                    chain_resp,
                    name=_sym_name(sym),
                    pass_id=str((self._last_scan or {}).get("pass_id") or "rescore"),
                )
                best = summarize_report(report)
            except Exception as exc:
                logger.debug("rescore %s: %s", sym, exc)
                continue
            hits.append(best)
            fetch_status, grade = self._fetch_status_for(best, None)
            self._symbol_states[sym] = {
                **(self._symbol_states.get(sym) or {}),
                "symbol": sym,
                "name": _sym_name(sym),
                "fetch_status": fetch_status,
                "grade": grade,
                "direction": best.get("chain_bias"),
                "chain_bias": best.get("chain_bias"),
                "pcr": best.get("oi_pcr"),
                "spot": best.get("spot"),
                "signal": (best.get("top_anomaly") or {}).get("label"),
                "setup_score": best.get("setup_score"),
                "flags": best.get("flags") or {},
                "error": None,
            }
        self._live_all_hits = hits
        self._ok_chain = max(int(self._ok_chain or 0), len(hits))
        total = int((self._last_scan or {}).get("universe_requested") or len(watch) or 1)
        board = self._publish_live_board(
            total=total,
            pass_id=str((self._last_scan or {}).get("pass_id") or "rescore"),
            phase="idle",
            persist=True,
        )
        self._last_board_persist_at = 0.0
        self._persist_last_scan()
        logger.info(
            "RESCORE_STORE hits=%s tradeable=%s watch=%s",
            len(hits),
            len(board.get("flagged") or []),
            len(board.get("watch") or []),
        )
        return board

    def _load_skip_symbols(self) -> None:
        """Load only confirmed invalid symbols; transient failures must retry."""
        try:
            from app.services import symbol_store as store
            from app.services.fno_stocks import is_valid_symbol

            meta = store.get_harvest_meta() or {}
            for s in meta.get("skip_symbols") or []:
                if isinstance(s, str) and s and not is_valid_symbol(s):
                    self._skip_symbols.add(s)
        except Exception:
            pass

    def _persist_skip_symbols(self) -> None:
        try:
            from app.services import symbol_store as store

            store.set_harvest_meta({"skip_symbols": sorted(self._skip_symbols)})
        except Exception:
            pass

    def _is_hard_fail(self, err: Optional[str]) -> bool:
        """Return True only when Fyers confirms that the symbol is invalid."""
        if not err:
            return False
        e = str(err).lower()
        return "invalid symbol" in e or ("invalid" in e and "symbol" in e)

    def _fetch_status_for(self, hit: Optional[Dict[str, Any]], err: Optional[str]) -> Tuple[str, Optional[str]]:
        """Return (fetch_status, grade). Grade is independent of fetch outcome."""
        if hit:
            return "SUCCESS", hit.get("grade") or "QUIET"
        if not err:
            return "SUCCESS", "QUIET"
        e = str(err).lower()
        if e in ("timeout", "invalid_symbol", "left_behind") or e.startswith("invalid_symbol"):
            return "SKIPPED", None
        if "quota" in e or "rate" in e or "429" in e or e == "wait":
            return "SKIPPED", None
        return "ERROR", None

    def _repartition_hits(self, all_hits: List[Dict[str, Any]]) -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict]]:
        try:
            from app.services.chain_anomaly import apply_universe_rank
            apply_universe_rank(all_hits)
        except Exception:
            pass

        def _rank(x: Dict[str, Any]) -> tuple:
            top = x.get("top_anomaly") or {}
            return (
                0 if x.get("grade") == "TRADEABLE" else 1,
                0 if (x.get("flags") or {}).get("unique") else 1,
                -float(x.get("unique_score") or 0),
                -float(x.get("setup_score") or 0),
                0 if x.get("trade") else 1,
                -float(top.get("oi_added") or 0),
                str(x.get("symbol") or ""),
            )

        radar = [h for h in all_hits if h.get("grade") == "TRADEABLE"]
        watch_list = [h for h in all_hits if h.get("grade") == "WATCH"]
        flow = [h for h in all_hits if h.get("grade") in ("TRADEABLE", "WATCH")]
        alert_box = [
            h for h in all_hits
            if (h.get("top_anomaly") or {}).get("type") in (
                "WALL_SUPPORT", "WALL_RESISTANCE", "CLUSTER", "OTM_SIZE", "WALL_SHIFT"
            )
        ]
        radar.sort(key=_rank)
        watch_list.sort(key=_rank)
        alert_box.sort(key=_rank)
        flow.sort(key=_rank)
        self._stamp_present_volume_flags(all_hits)
        return radar, watch_list, alert_box, flow

    def _stamp_present_volume_flags(self, hits: List[Dict[str, Any]]) -> None:
        """Fill present-session option volume on every harvest row. Do not rewrite engine flags."""
        for h in hits:
            tot = 0.0
            try:
                tot = float(
                    ((h.get("flags") or {}).get("opt_volume"))
                    or ((h.get("volume") or {}).get("total_volume"))
                    or h.get("chain_volume")
                    or 0
                )
            except (TypeError, ValueError):
                tot = 0.0
            flags = dict(h.get("flags") or {})
            flags["opt_volume"] = tot
            h["flags"] = flags
            h["chain_volume"] = tot

    def _screen_rows(self, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Slim universe for the middle AND-filter pane (includes QUIET)."""
        out: List[Dict[str, Any]] = []
        seen = set()
        for h in hits:
            sym = h.get("symbol")
            if not sym or sym in seen:
                continue
            seen.add(sym)
            flags = h.get("flags") or {}
            top = h.get("top_anomaly") or {}
            out.append({
                "symbol": sym,
                "name": h.get("name"),
                "grade": h.get("grade"),
                "chain_bias": h.get("chain_bias"),
                "setup_score": h.get("setup_score"),
                "flags": flags,
                "spot": h.get("spot"),
                "put_wall": h.get("put_wall"),
                "call_wall": h.get("call_wall"),
                "chain_volume": h.get("chain_volume")
                or (h.get("volume") or {}).get("total_volume")
                or flags.get("opt_volume"),
                "session": h.get("session") or {},
                "top_anomaly": {
                    "type": top.get("type"),
                    "oi_added": top.get("oi_added"),
                    "volume": top.get("volume"),
                    "strike": top.get("strike"),
                    "vor": top.get("vor") or flags.get("vor"),
                    "oi_velocity": top.get("oi_velocity"),
                    "label": top.get("label"),
                } if top else None,
                "top_anomaly_label": h.get("top_anomaly_label") or top.get("label"),
                "vor": top.get("vor") or flags.get("vor"),
                "ts": h.get("ts"),
                "unique_score": h.get("unique_score") or flags.get("unique_score"),
                "why_not": h.get("why_not"),
            })
        try:
            from app.services.chain_anomaly import cap_screen_by_tag
            return cap_screen_by_tag(out)
        except Exception:
            return out

    def _live_board_shell(self, *, total: int, pass_id: str, phase: str) -> Dict[str, Any]:
        flagged, watch_list, alert_box, flow = self._repartition_hits(self._live_all_hits)
        skipped = list(self._skipped_syms)
        errors = list(self._error_syms)
        ok_chain = int(self._ok_chain)
        attempted = int(self._attempted)
        failed_remaining = list(self._failed_remaining)
        quiet_n = sum(1 for h in self._live_all_hits if h.get("grade") == "QUIET")
        return {
            "success": True,
            "engine": "v6-anomaly",
            "phase": phase,
            "pass_id": pass_id,
            "scanned": attempted,
            "attempted": attempted,
            "ok_chain": ok_chain,
            "hits": len(flagged) + len(watch_list),
            "universe_requested": total,
            "total": total,
            "total_flagged": len(flagged),
            "partial": ok_chain < total,
            "flagged": flagged,
            "tradeable": flagged,
            "watch": watch_list,
            "bullish": [h for h in flow if h.get("chain_bias") == "BULLISH"],
            "bearish": [h for h in flow if h.get("chain_bias") == "BEARISH"],
            "top": (flagged or flow)[:8],
            "flow": flow,
            "unique": [h for h in flagged if (h.get("flags") or {}).get("unique")][:12],
            "screen": self._screen_rows(self._live_all_hits),
            "alert_box": alert_box,
            "quiet_count": quiet_n,
            "all_hits": [h for h in self._live_all_hits if h.get("grade") in ("TRADEABLE", "WATCH")],
            "skipped": skipped,
            "errors": errors,
            "symbol_states": list(self._symbol_states.values()),
            "scan_running": True,
            "retry_attempted": 0,
            "retry_recovered": 0,
            "failed_remaining": failed_remaining,
            "grade_counts": {
                "TRADEABLE": len(flagged),
                "WATCH": len(watch_list),
                "QUIET": quiet_n,
            },
            "completion_pct": round(100.0 * min(attempted, total) / max(total, 1), 1),
            "timestamp": datetime.now().isoformat(),
            "market_hours": self._is_market_hours(),
        }

    def _publish_live_board(
        self,
        *,
        total: int,
        pass_id: str,
        phase: str,
        persist: bool = True,
    ) -> Dict[str, Any]:
        board = self._live_board_shell(total=total, pass_id=pass_id, phase=phase)
        board["ideas"] = [h for h in (board.get("tradeable") or board.get("flagged") or []) if h.get("trade")]
        board["idea_counts"] = {"active": len(board["ideas"])}
        self._last_scan = board
        self._last_scan_at = datetime.now()
        if persist:
            now = time.time()
            # In-memory board is always current; Redis persist is throttled so
            # 4 workers don't serialize on a growing snapshot.
            if now - float(self._last_board_persist_at or 0) >= 0.6:
                self._last_board_persist_at = now
                self._persist_last_scan()
        return board

    def _upsert_symbol_state(
        self,
        symbol: str,
        *,
        hit: Optional[Dict[str, Any]] = None,
        err: Optional[str] = None,
        fetch_status: str,
        grade: Optional[str] = None,
        ms: int = 0,
        retries: int = 0,
        quota_wait: float = 0.0,
        cache_hit: bool = False,
        total: int = 0,
        pass_id: str = "",
        phase: str = "chains",
    ) -> None:
        row = hit or {}
        self._symbol_states[symbol] = {
            "symbol": symbol,
            "name": _sym_name(symbol),
            "fetch_status": fetch_status,
            "grade": grade,
            "ms": int(ms or 0),
            "error": (str(err)[:120] if err else None),
            "retries": int(retries or 0),
            "lis": 0,
            "strike": (row.get("trade") or {}).get("strike") or (row.get("top_anomaly") or {}).get("strike"),
            "type": (row.get("trade") or {}).get("instrument") or (row.get("top_anomaly") or {}).get("side"),
            "direction": row.get("chain_bias"),
            "pcr": row.get("oi_pcr") or (row.get("structure") or {}).get("oi_pcr"),
            "spot": row.get("spot"),
            "signal": (row.get("top_anomaly") or {}).get("label") or row.get("regime"),
            "chain_bias": row.get("chain_bias"),
            "why_not": row.get("why_not"),
            "setup_score": row.get("setup_score"),
            "flags": row.get("flags") or {},
        }
        self._harvest_symbol_telemetry.append({
            "harvest_id": pass_id or self._harvest_id,
            "symbol": symbol,
            "latency": int(ms or 0),
            "status": fetch_status,
            "retry_count": int(retries or 0),
            "quota_wait": round(float(quota_wait or 0.0), 2),
            "cache_hit": bool(cache_hit),
            "grade": grade,
        })
        if hit:
            self._live_all_hits = [
                r for r in self._live_all_hits if r.get("symbol") != symbol
            ]
            self._live_all_hits.append(hit)
        try:
            from app.services import symbol_store as store
            store.put(symbol, {
                "radar": {
                    "grade": grade,
                    "chain_bias": (hit or {}).get("chain_bias"),
                    "hit": bool(hit) and (hit or {}).get("grade") in ("TRADEABLE", "WATCH"),
                    "fetch_status": fetch_status,
                    "ts": time.time(),
                }
            })
        except Exception:
            pass
        self._publish_live_board(total=total, pass_id=pass_id, phase=phase, persist=True)

    def build_harvest_priority(self, watch: List[str]) -> Tuple[List[str], List[str]]:
        """Ordered harvest queue + TOP 34 set (indices + TOP_FNO_STOCKS)."""
        watch_set = set(watch)
        seen: set = set()
        ordered: List[str] = []

        def _add(syms: List[str]) -> None:
            for s in syms:
                if s in watch_set and s not in seen:
                    seen.add(s)
                    ordered.append(s)

        last = self._last_scan or {}
        locked: List[str] = []
        try:
            book = get_idea_book().board(limit=25)
            for idea in (book.get("active") or []) + (book.get("confirmed") or []):
                if idea.get("symbol"):
                    locked.append(str(idea["symbol"]))
        except Exception:
            pass
        prev_hits: List[str] = []
        for row in (last.get("flagged") or []):
            if row.get("grade") in ("A+", "A") and row.get("symbol"):
                prev_hits.append(str(row["symbol"]))

        _add(locked)
        try:
            _add(list(self._hot_symbols or []))
        except Exception:
            pass
        _add(prev_hits)
        _add(filter_valid_symbols(list(FNO_INDICES)))
        _add(filter_valid_symbols(list(TOP_FNO_STOCKS)))
        top34 = filter_valid_symbols(list(dict.fromkeys([*FNO_INDICES, *TOP_FNO_STOCKS])))
        top34 = [s for s in top34 if s in watch_set]
        rest = [s for s in watch if s not in seen]
        _add(rest)
        for s in watch:
            if s not in seen:
                ordered.append(s)
        return ordered, top34

    def _harvest_futures_batch(self, symbols: List[str]) -> int:
        """One quotes call per ≤50 futures — not N serial REST calls."""
        from app.services.levels import (
            classify_futures_buildup,
            fut_symbol_for,
            get_levels_service,
        )
        from app.services import symbol_store as store

        def _f(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        mapping: Dict[str, str] = {}
        futs: List[str] = []
        for s in dict.fromkeys([x for x in symbols if x]):
            fs = fut_symbol_for(s)
            if not fs:
                continue
            mapping[fs] = s
            futs.append(fs)
        if not futs:
            return 0
        calls = 0
        levels = get_levels_service()
        for i in range(0, len(futs), 50):
            chunk = futs[i: i + 50]
            calls += 1
            try:
                q = self.market_service.get_quotes(chunk)
            except Exception as exc:
                logger.warning("futures batch %s: %s", i, exc)
                continue
            by_name = {}
            for item in q.get("data") or []:
                n = str(item.get("n") or "")
                by_name[n] = item
            for fut in chunk:
                item = by_name.get(fut)
                if item is None:
                    for n, it in by_name.items():
                        if fut in n or n.endswith(fut.split(":")[-1]):
                            item = it
                            break
                if item is None and q.get("data") and len(chunk) == 1:
                    item = q["data"][0]
                if not item:
                    continue
                v = item.get("v") or {}
                lp = _f(v.get("lp"))
                chp = _f(v.get("chp"))
                oi = v.get("oi") if v.get("oi") is not None else v.get("open_interest")
                oi_f = _f(oi)
                prev_oi = v.get("poi") or v.get("prev_oi") or v.get("previous_oi")
                under = mapping.get(fut)
                if prev_oi is not None and oi_f is not None:
                    oi_chg = oi_f - _f(prev_oi)
                elif under and oi_f is not None and under in levels._fut_last_oi:
                    oi_chg = oi_f - levels._fut_last_oi[under]
                else:
                    oi_chg = None
                if under and oi_f is not None:
                    levels._fut_last_oi[under] = oi_f
                packed = classify_futures_buildup(chp, oi_chg, oi_f)
                packed.update({"ok": True, "symbol": fut, "ltp": lp, "change_pct": chp})
                if under:
                    store.put_futures(under, packed)
                    levels._fut_cache[under] = (time.time(), packed)
        return calls

    def _stop_history_sweeper(self) -> None:
        """Pause the process-wide sweeper so it cannot compete with chain harvest."""
        self._history_stop.set()
        try:
            from app.services.history_sweeper import get_history_sweeper
            get_history_sweeper().pause()
        except Exception:
            pass

    def _start_history_sweeper(self, symbols: List[str]) -> None:
        """Start leftover-RPM history fills AFTER chains finish. Never at boot."""
        try:
            from app.services.history_sweeper import get_history_sweeper
            from app.services.rate_limiter import get_fyers_limiter

            sw = get_history_sweeper()
            sw.nudge(list(symbols or []))
            if get_fyers_limiter().in_cooldown:
                sw.pause()
                logger.info("history sweeper stays paused — fyers cooldown")
                return
            sw.start()
            sw.resume()
        except Exception as exc:
            logger.debug("history sweeper start: %s", exc)

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

    def _structural_candidate(self, chain: List[Dict[str, Any]], spot: float) -> Optional[Dict[str, Any]]:
        """Highest volume/OI ATM-ish contract when unusual-flow filters find nothing."""
        best: Optional[Dict[str, Any]] = None
        best_score = -1.0
        if not chain or not spot:
            return None
        for row in chain:
            strike = row.get("strike_price")
            if not strike or strike <= 0:
                continue
            atm_dist_pct = abs(float(strike) - float(spot)) / float(spot) * 100
            if atm_dist_pct > MAX_ATM_DISTANCE_PCT:
                continue
            for opt_type, key in [("CE", "call"), ("PE", "put")]:
                opt = row.get(key)
                if not opt:
                    continue
                oi = float(opt.get("oi") or 0)
                volume = float(opt.get("volume") or 0)
                ltp = float(opt.get("ltp") or 0)
                if oi <= 0 and volume <= 0:
                    continue
                score = volume + oi * 0.02
                if score <= best_score:
                    continue
                best_score = score
                ltp_chg = float(opt.get("chg_pct") or 0)
                oi_pct = derive_oi_change_pct(opt)
                if opt_type == "CE":
                    direction = "BULLISH" if ltp_chg >= 0 else "BEARISH"
                else:
                    direction = "BEARISH" if ltp_chg >= 0 else "BULLISH"
                best = {
                    "strike": strike,
                    "opt_type": opt_type,
                    "opt": opt,
                    "atm_dist_pct": atm_dist_pct,
                    "oi_change_pct": oi_pct,
                    "ltp_chg_pct": ltp_chg,
                    "oi": oi,
                    "volume": volume,
                    "ltp": ltp,
                    "iv": float(opt.get("iv") or 0),
                    "prelim_signal": {
                        "signal": "ACCUMULATION",
                        "label": "Chain structure",
                        "icon": "🔵",
                        "color": "blue",
                        "direction": direction,
                    },
                }
        return best

    def _process_option_chain(
        self,
        symbol: str,
        underlying: Dict[str, Any],
        strike_count: int = 10,
        *,
        fetch_vol_history: bool = False,
        enrich_underlying: bool = True,
        attach_heavy: bool = True,
        attach_process: bool = True,
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
                oi_change_pct = derive_oi_change_pct(opt)
                ltp_chg_pct = float(opt.get("chg_pct") or 0)
                oi = float(opt.get("oi") or 0)
                volume = float(opt.get("volume") or 0)
                ltp = float(opt.get("ltp") or 0)
                iv = float(opt.get("iv") or 0)

                if oi <= 0 and volume <= 0:
                    continue
                if (
                    abs(oi_change_pct) < MIN_OI_CHANGE_PCT
                    and volume < MIN_OPTION_VOLUME
                    and abs(ltp_chg_pct) < MIN_PREMIUM_CHG_PCT
                ):
                    continue

                prelim_sig = classify_signal(
                    oi_change_pct, ltp_chg_pct, ul_chg_pct, opt_type=opt_type
                )
                if prelim_sig.get("signal") == "NEUTRAL":
                    if volume >= MIN_OPTION_VOLUME and abs(ltp_chg_pct) >= MIN_PREMIUM_CHG_PCT:
                        if opt_type == "CE":
                            direction = "BULLISH" if ltp_chg_pct > 0 else "BEARISH"
                            label = "Call premium bid" if ltp_chg_pct > 0 else "Call premium dump"
                        else:
                            direction = "BEARISH" if ltp_chg_pct > 0 else "BULLISH"
                            label = "Put premium bid" if ltp_chg_pct > 0 else "Put premium dump"
                        prelim_sig = {
                            "signal": "ACCUMULATION",
                            "label": label,
                            "icon": "🔵",
                            "color": "blue",
                            "direction": direction,
                        }
                    elif volume >= MIN_OPTION_VOLUME or oi >= 50_000:
                        prelim_sig = {
                            "signal": "ACCUMULATION",
                            "label": "Tape / OI build",
                            "icon": "🔵",
                            "color": "blue",
                            "direction": "NEUTRAL",
                        }
                    else:
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
            fallback = self._structural_candidate(chain, spot)
            if fallback:
                candidates = [fallback]
            else:
                try:
                    get_idea_book().ingest_neutral(symbol, float(spot or 0))
                except Exception:
                    pass
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
            fallback = self._structural_candidate(chain, spot)
            if fallback:
                row = build_scored_contract(
                    symbol=symbol,
                    name=sym_name,
                    nearest_expiry=nearest_expiry,
                    cand=fallback,
                    signal=fallback.get("prelim_signal") or classify_signal(
                        fallback["oi_change_pct"], fallback["ltp_chg_pct"], ul_chg_pct,
                        opt_type=fallback["opt_type"],
                    ),
                    vol_3day_avg=0.0,
                    vol_spike_ratio=1.0,
                    vol_spike_source="chain_median",
                    spot=float(spot or 0),
                    ul_chg_pct=ul_chg_pct,
                    vwap_dev=vwap_dev,
                    above_ema=above_ema,
                    cluster_hits=1,
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
        if chain_resp.get("pcr") is not None:
            best["pcr"] = chain_resp.get("pcr")
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

        if not attach_process:
            return best

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
        """Pass A — batched quotes (≤50) into the symbol store.

        Skipped when the WebSocket is connected (ticks may not have arrived
        yet — REST quotes still burn quota). Also skipped in cooldown.
        """
        from app.services.fno_stocks import filter_valid_symbols
        from app.services.rate_limiter import get_fyers_limiter

        if get_fyers_limiter().in_cooldown:
            logger.info("harvest quotes skip — fyers cooldown")
            return
        try:
            from app.services.spot_stream import get_spot_stream
            stream = get_spot_stream()
            if stream.is_connected() or stream.is_live():
                logger.info("harvest quotes skip — websocket connected")
                return
        except Exception:
            pass

        universe = filter_valid_symbols(list(dict.fromkeys([
            *symbols,
            *FNO_INDICES,
            "NSE:INDIAVIX-INDEX",
        ])))
        logger.info("harvest quotes pass n=%s", len(universe))
        for i in range(0, len(universe), 50):
            if get_fyers_limiter().in_cooldown:
                logger.info("harvest quotes abort — cooldown after chunk %s", i)
                return
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
        from app.services.rate_limiter import get_fyers_limiter

        if not self._is_authenticated():
            return {
                "success": False,
                "error": "Not authenticated with Fyers API",
                "flagged": [],
                "watch": [],
                "alert_box": [],
            }
        if not self._scan_lock.acquire(blocking=False):
            return {
                "success": False,
                "error": "Scan already running",
                "flagged": [],
                "watch": [],
                "alert_box": [],
                "scan_running": True,
            }

        self._scan_running = True
        self._scan_heartbeat = time.time()
        self._rescored_store = False
        self._stop_history_sweeper()
        self._load_skip_symbols()
        raw_watch = filter_valid_symbols(symbols or ALL_FNO_WATCHLIST)
        excluded = [s for s in raw_watch if s in self._skip_symbols]
        watch = [s for s in raw_watch if s not in self._skip_symbols]
        total = len(raw_watch)
        all_hits: List[Dict] = []
        errors: List[str] = []
        scanned = 0
        rate_limited_skips = 0
        pass_id = f"h{int(time.time())}"
        limiter = get_fyers_limiter()
        self._harvest_id = pass_id
        self._harvest_t0 = time.perf_counter()
        self._harvest_grants0 = int(limiter.total_grants)
        self._harvest_trips0 = int(limiter.trip_count)
        self._hydrate_last_scan_from_redis()
        prev = self._last_scan or {}
        seeded: List[Dict[str, Any]] = []
        seen_seed = set()
        for row in (prev.get("flagged") or []) + (prev.get("watch") or []) + (prev.get("alert_box") or []):
            sym = (row or {}).get("symbol")
            if not sym or sym in seen_seed:
                continue
            seen_seed.add(sym)
            seeded.append(row)
        self._live_all_hits = seeded
        prev_states: Dict[str, Dict[str, Any]] = {}
        for row in (prev.get("symbol_states") or []):
            sym = (row or {}).get("symbol")
            if sym:
                prev_states[str(sym)] = dict(row)
        self._symbol_states = prev_states
        self._ok_chain = 0
        self._attempted = 0
        self._skipped_syms = list(excluded)
        self._error_syms = []
        self._harvest_symbol_telemetry = []
        self._failed_remaining = list(excluded)
        self._attempted = len(excluded)
        for s in excluded:
            self._symbol_states[s] = {
                "symbol": s,
                "name": _sym_name(s),
                "fetch_status": "SKIPPED",
                "grade": (self._symbol_states.get(s) or {}).get("grade"),
                "ms": 0,
                "error": "left_behind",
                "retries": 0,
            }
        _hw = store.harvest_writer()
        _hw.__enter__()
        quotes_phase = "cooldown" if limiter.in_cooldown else "quotes"
        store.set_harvest_meta({
            "running": True,
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "scanned": 0,
            "total": total,
            "current": None,
            "pass_id": pass_id,
            "phase": quotes_phase,
            "ok_chain": 0,
            "attempted": len(excluded),
            "cooldown_remaining": round(limiter.cooldown_remaining, 1),
        })
        self._publish_live_board(total=total, pass_id=pass_id, phase=quotes_phase)
        try:
            self._harvest_quotes_pass(watch)
        except Exception as exc:
            logger.warning("harvest quotes pass failed: %s", exc)

        def _progress(sym: str, flagged_row=None, err=None, *, status: str = "ok", ms: int = 0):
            if progress_callback:
                try:
                    progress_callback(self._attempted, total, sym, flagged_row, err, status, ms)
                except TypeError:
                    try:
                        progress_callback(self._attempted, total, sym, flagged_row, err)
                    except Exception:
                        pass
                except Exception:
                    pass

        _tl = threading.local()

        def _scan_one(
            sym: str,
            *,
            chain_only: bool = False,
            force_chain: bool = False,
        ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
            from app.services import symbol_store as _st
            if not _st.is_harvest_writer():
                with _st.harvest_writer():
                    return _scan_one(sym, chain_only=chain_only, force_chain=force_chain)
            if not is_valid_symbol(sym):
                return None, "invalid_symbol"
            stored = _st.get_chain(sym, strike_count) or {}
            have_store = bool(stored.get("success") and len(stored.get("chain") or []) >= 2)
            t_http = time.perf_counter()
            if get_fyers_limiter().in_cooldown:
                if have_store and not force_chain:
                    chain_resp = stored
                    try:
                        _tl.http_ms = 0
                        _tl.limiter_wait = 0.0
                        _tl.cache_hit = True
                    except Exception:
                        pass
                else:
                    return None, "rate_limit"
            else:
                chain_resp = self.market_service.get_option_chain(
                    sym, strike_count, force_refresh=force_chain
                )
                try:
                    _tl.http_ms = int((time.perf_counter() - t_http) * 1000)
                    _tl.limiter_wait = get_fyers_limiter().last_wait_s()
                    _tl.cache_hit = bool(
                        (chain_resp or {}).get("_store") or (chain_resp or {}).get("_cache") == "hit"
                    )
                except Exception:
                    pass
            underlying = self._underlying_from_store(sym)
            if not underlying and not chain_only:
                underlying = self._get_underlying_data(sym, light=True)
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
            from app.services.chain_desk import evaluate
            from app.services.chain_anomaly import summarize_report

            try:
                report = evaluate(
                    sym, chain_resp, name=_sym_name(sym), pass_id=self._harvest_id
                )
                summary = summarize_report(report)
            except Exception as exc:
                logger.warning("anomaly evaluate %s: %s", sym, exc)
                return None, f"analyze:{exc}"[:120]
            if opt_type_filter:
                inst = ((summary.get("trade") or {}).get("instrument") or "")
                if inst and inst != opt_type_filter:
                    return None, None
            return summary, None

        def _weight_hit(hit: Dict[str, Any]) -> Dict[str, Any]:
            return hit

        from app.core.config import get_settings
        from app.services.rate_limiter import HARVEST_MIN_INTERVAL, IDLE_MIN_INTERVAL

        try:
            workers_n = int(get_settings().harvest_chain_workers or CHAIN_WORKERS)
        except Exception:
            workers_n = CHAIN_WORKERS
        workers_n = max(1, min(workers_n, 4))

        watch, top34 = self.build_harvest_priority(watch)
        top34_set = set(top34)
        limiter.set_min_interval(HARVEST_MIN_INTERVAL)

        logger.info(
            "HARVEST_START pass=%s requested=%s walk=%s left_behind=%s workers=%s rps=%.1f top34=%s",
            pass_id, total, len(watch), len(excluded), workers_n, HARVEST_RPS, len(top34),
        )
        store.set_harvest_meta({
            "phase": "chains",
            "running": True,
            "total": total,
            "workers": workers_n,
            "left_behind": len(excluded),
            "skip_symbols": sorted(self._skip_symbols),
        })
        failed_syms: List[str] = list(excluded)
        retry_attempted = 0
        retry_recovered = 0
        top_tier_elapsed_sec: Optional[float] = None
        rpm_peak = 0
        futures_calls = 0

        def _work(sym: str) -> Dict[str, Any]:
            t0 = time.perf_counter()
            retries = 0
            try:
                hit, err = _scan_one(sym, chain_only=True, force_chain=False)
                while err and retries < 2 and not self._is_hard_fail(err):
                    if "rate_limit" in str(err).lower() or "429" in str(err).lower():
                        break
                    retries += 1
                    time.sleep(0.5 * retries)
                    hit, err = _scan_one(sym, chain_only=True, force_chain=True)
                if err and "invalid symbol" in str(err).lower():
                    mark_invalid_symbol(sym)
            except Exception as exc:
                hit, err = None, str(exc)[:120]
                if "invalid symbol" in str(exc).lower():
                    mark_invalid_symbol(sym)
            return {
                "symbol": sym,
                "hit": hit,
                "err": err,
                "retries": retries,
                "ms": int((time.perf_counter() - t0) * 1000),
                "http_ms": int(getattr(_tl, "http_ms", 0) or 0),
                "limiter_wait": float(getattr(_tl, "limiter_wait", 0) or 0),
                "cache_hit": bool(getattr(_tl, "cache_hit", False)),
            }

        def _accept(res: Dict[str, Any]) -> None:
            nonlocal scanned, top_tier_elapsed_sec, rpm_peak, retry_attempted, retry_recovered, rate_limited_skips
            sym = res["symbol"]
            hit = res.get("hit")
            err = res.get("err")
            ms = int(res.get("ms") or 0)
            retries_this = 0
            try:
                from app.services.rate_limiter import is_rate_limit_error
                if res.get("err") and is_rate_limit_error(res.get("err")):
                    rate_limited_skips += 1
            except Exception:
                pass
            scanned += 1
            self._attempted = len(excluded) + scanned
            self._scan_heartbeat = time.time()
            try:
                rpm_peak = max(rpm_peak, int(limiter.requests_last_minute()))
            except Exception:
                pass
            if hit:
                hit = _weight_hit(hit)
                all_hits.append(hit)
                self._ok_chain += 1
                fetch_status, grade = self._fetch_status_for(hit, None)
                prog_status = "hit"
                logger.info(
                    "CHAIN_DONE pass=%s symbol=%s latency_ms=%s grade=%s",
                    pass_id, sym, ms, grade,
                )
            elif err:
                errors.append(f"{sym}: {err}")
                if self._is_hard_fail(err):
                    if sym not in failed_syms:
                        failed_syms.append(sym)
                    self._skip_symbols.add(sym)
                    self._failed_remaining = list(failed_syms)
                fetch_status, grade = self._fetch_status_for(None, err)
                if fetch_status == "SKIPPED":
                    self._skipped_syms.append(sym)
                else:
                    self._error_syms.append(f"{sym}: {err}")
                prog_status = "err"
                logger.info(
                    "CHAIN_SKIP pass=%s symbol=%s reason=%s left_behind=%s",
                    pass_id, sym, err, self._is_hard_fail(err),
                )
            else:
                self._ok_chain += 1
                fetch_status, grade = "SUCCESS", "NO_SIGNAL"
                prog_status = "skip"
                logger.info(
                    "CHAIN_DONE pass=%s symbol=%s latency_ms=%s grade=NO_SIGNAL",
                    pass_id, sym, ms,
                )
            t_pub = time.perf_counter()
            self._upsert_symbol_state(
                sym,
                hit=hit,
                err=err,
                fetch_status=fetch_status,
                grade=grade,
                ms=ms,
                retries=retries_this,
                quota_wait=float(res.get("limiter_wait") or 0),
                cache_hit=bool(res.get("cache_hit")),
                total=total,
                pass_id=pass_id,
                phase="chains",
            )
            _progress(
                sym,
                flagged_row=hit if hit else None,
                err=err,
                status=prog_status,
                ms=ms,
            )
            tel = self._harvest_symbol_telemetry[-1] if self._harvest_symbol_telemetry else {}
            tel["http_latency_ms"] = int(res.get("http_ms") or 0)
            tel["limiter_wait_ms"] = int(float(res.get("limiter_wait") or 0) * 1000)
            tel["processing_ms"] = max(0, ms - int(tel.get("http_latency_ms") or 0))
            tel["publish_ms"] = int((time.perf_counter() - t_pub) * 1000)
            tel["total_symbol_ms"] = ms
            store.set_harvest_meta({
                "scanned": scanned,
                "attempted": self._attempted,
                "ok_chain": self._ok_chain,
                "current": sym,
                "phase": "chains",
            })
            if top_tier_elapsed_sec is None:
                done_top = [s for s in top34_set if s in self._symbol_states and self._symbol_states[s].get("fetch_status") != "FETCHING"]
                if len(done_top) >= len(top34_set) and top34_set:
                    top_tier_elapsed_sec = time.perf_counter() - self._harvest_t0
                    logger.info("TOP_TIER_DONE pass=%s elapsed_sec=%.2f n=%s", pass_id, top_tier_elapsed_sec, len(top34_set))

        try:
            pool = ThreadPoolExecutor(max_workers=workers_n, thread_name_prefix="radar-sym")
            try:
                futs = {pool.submit(_work, sym): sym for sym in watch}
                for fut in as_completed(futs):
                    self._scan_heartbeat = time.time()
                    try:
                        res = fut.result()
                    except Exception as exc:
                        res = {"symbol": futs[fut], "hit": None, "err": str(exc)[:120], "retries": 0, "ms": 0}
                    _accept(res)
            finally:
                pool.shutdown(wait=True, cancel_futures=False)

            scored = [h.get("symbol") for h in all_hits if h.get("symbol")]
            try:
                universe_futs = [s for s in watch if s in self._symbol_states]
                if universe_futs and not limiter.in_cooldown:
                    futures_calls = self._harvest_futures_batch(universe_futs)
            except Exception as fut_exc:
                logger.debug("futures batch: %s", fut_exc)
            try:
                from app.services.chain_desk import reevaluate_with_stored_futures
                from app.services.chain_anomaly import summarize_report as _sum

                refreshed: List[Dict[str, Any]] = []
                seen = set()
                for h in list(self._live_all_hits):
                    sym_r = h.get("symbol")
                    if not sym_r or sym_r in seen:
                        continue
                    seen.add(sym_r)
                    try:
                        full = reevaluate_with_stored_futures(sym_r)
                        refreshed.append(_sum(full) if full else h)
                    except Exception:
                        refreshed.append(h)
                if refreshed:
                    self._live_all_hits = refreshed
                    all_hits[:] = [r for r in refreshed if r.get("grade") in ("TRADEABLE", "WATCH", "QUIET")]
                    self._publish_live_board(total=total, pass_id=pass_id, phase="futures", persist=True)
            except Exception as re_exc:
                logger.debug("futures reanalyze: %s", re_exc)

            got = {h.get("symbol") for h in all_hits}
            failed_syms = [s for s in failed_syms if s not in got]
            self._failed_remaining = failed_syms
            for s in failed_syms:
                self._skip_symbols.add(s)
            self._persist_skip_symbols()
            self._last_board_persist_at = 0.0
            self._persist_last_scan()
        except Exception:
            try:
                limiter.set_min_interval(IDLE_MIN_INTERVAL)
            except Exception:
                pass
            try:
                _hw.__exit__(None, None, None)
            except Exception:
                pass
            raise
        finally:
            try:
                limiter.set_min_interval(IDLE_MIN_INTERVAL)
            except Exception:
                pass
            self._scan_running = False
            try:
                if self._scan_lock.locked():
                    self._scan_lock.release()
            except RuntimeError:
                pass

        self._live_all_hits = list(self._live_all_hits or all_hits)
        flagged, watch_list, alert_box, flow = self._repartition_hits(self._live_all_hits)

        elapsed_ms = int((time.perf_counter() - self._harvest_t0) * 1000)
        fyers_requests = int(limiter.total_grants) - int(self._harvest_grants0)
        trips = int(limiter.trip_count) - int(self._harvest_trips0)
        ok_chain = int(self._ok_chain)
        attempted = int(self._attempted or scanned)
        partial = attempted < total
        no_signal = sum(1 for s in self._symbol_states.values() if s.get("grade") == "NO_SIGNAL")
        try:
            rpm_peak = max(rpm_peak, int(limiter.rpm_peak), int(limiter.requests_last_minute()))
        except Exception:
            pass

        logger.info(
            "HARVEST_DONE pass=%s attempted=%s ok=%s skipped=%s errors=%s elapsed_ms=%s rpm_peak=%s cooldowns=%s workers=%s top_tier_sec=%s futures_batches=%s",
            pass_id, attempted, ok_chain, len(self._skipped_syms), len(self._error_syms),
            elapsed_ms, rpm_peak, trips, workers_n,
            round(top_tier_elapsed_sec, 2) if top_tier_elapsed_sec is not None else None,
            futures_calls,
        )
        board = get_idea_book().board(limit=8)
        telemetry = {
            "harvest_id": pass_id,
            "requested": total,
            "total_symbols": total,
            "attempted": attempted,
            "successful": ok_chain,
            "ok_chain": ok_chain,
            "no_signal": no_signal,
            "skipped": len(self._skipped_syms),
            "errors": len(self._error_syms),
            "hits": len(all_hits),
            "elapsed_ms": elapsed_ms,
            "elapsed_sec": round(elapsed_ms / 1000.0, 2),
            "top_tier_elapsed_sec": round(top_tier_elapsed_sec, 2) if top_tier_elapsed_sec is not None else None,
            "fyers_requests": fyers_requests,
            "futures_batches": futures_calls,
            "workers": workers_n,
            "rps": HARVEST_RPS,
            "429_count": trips,
            "rate_limit_events": trips,
            "cooldown_count": trips,
            "rpm_peak": rpm_peak,
            "symbols": list(self._harvest_symbol_telemetry),
        }
        result = {
            "success": True,
            "engine": "v6-anomaly",
            "phase": "idle",
            "pass_id": pass_id,
            "scanned": attempted,
            "attempted": attempted,
            "ok_chain": ok_chain,
            "hits": len(all_hits),
            "universe_requested": total,
            "total": total,
            "total_flagged": len(flagged),
            "flagged": flagged,
            "watch": watch_list,
            "flow": flow,
            "alert_box": alert_box,
            "screen": self._screen_rows(self._live_all_hits or all_hits),
            "all_hits": all_hits,
            "retry_attempted": retry_attempted,
            "retry_recovered": retry_recovered,
            "failed_remaining": failed_syms,
            "skipped": list(self._skipped_syms),
            "symbol_states": list(self._symbol_states.values()),
            "ideas": board.get("active") or [],
            "ideas_confirmed": board.get("confirmed") or [],
            "ideas_bullish": board.get("bullish") or [],
            "ideas_bearish": board.get("bearish") or [],
            "ideas_pullbacks": board.get("pullbacks") or [],
            "ideas_watch": board.get("watch") or [],
            "ideas_conflict": board.get("conflict") or [],
            "idea_counts": board.get("counts") or {},
            "tradeable": flagged,
            "bullish": [h for h in flow if h.get("chain_bias") == "BULLISH"],
            "bearish": [h for h in flow if h.get("chain_bias") == "BEARISH"],
            "top": flagged[:8] if flagged else flow[:8],
            "quiet_count": sum(1 for h in self._live_all_hits if h.get("grade") == "QUIET"),
            "grade_counts": {
                "TRADEABLE": len(flagged),
                "WATCH": len(watch_list),
                "QUIET": sum(1 for h in self._live_all_hits if h.get("grade") == "QUIET"),
            },
            "flow_count": len(flow),
            "errors": errors,
            "rate_limited_skips": rate_limited_skips,
            "partial": partial,
            "scan_running": False,
            "completion_pct": round(100.0 * min(attempted, total) / max(total, 1), 1),
            "timestamp": datetime.now().isoformat(),
            "market_hours": self._is_market_hours(),
            "telemetry": telemetry,
            "rules": {
                "description": (
                    "v6 anomaly: whole-chain structure (PCR/walls/pin/skew) + "
                    "futures OI + size/cluster flags. WAIT unless they agree "
                    "and persist one more harvest. No LIS."
                ),
            },
        }
        # Incremental board is already live. Always publish the finished snapshot
        # so a partial walk remains visible (ok_chain < total is valid).
        if symbols is None or total >= len(filter_valid_symbols(ALL_FNO_WATCHLIST)) or not self._last_scan:
            self._last_scan = result
            self._last_scan_at = datetime.now()
            self._persist_last_scan()
            if not self._is_market_hours():
                try:
                    self.pin_last_session()
                except Exception:
                    pass
        try:
            self._rebuild_hv_index()
        except Exception:
            pass
        try:
            self._start_history_sweeper(watch)
        except Exception as hist_exc:
            logger.debug("history sweeper start: %s", hist_exc)
        try:
            store.set_harvest_meta({
                "running": False,
                "finished_at": datetime.now().isoformat(),
                "scanned": scanned,
                "attempted": attempted,
                "ok_chain": ok_chain,
                "total": total,
                "current": None,
                "pass_id": pass_id,
                "phase": "idle",
                "flagged": result.get("total_flagged"),
                "retry_attempted": retry_attempted,
                "retry_recovered": retry_recovered,
                "failed_remaining": failed_syms,
                "skip_symbols": sorted(self._skip_symbols),
                "partial": partial,
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
        live: bool = False,
    ) -> Dict[str, Any]:
        from app.services import symbol_store as store

        try:
            snap = store.get(symbol) or {}
            spot = store.get_spot(symbol) or snap.get("spot") or {}
            chain_resp = store.get_chain(symbol, strike_count) or {}
            m15 = store.get_history(symbol, "15", min_bars=1) or []
            derived = snap.get("derived") or {}
            ltp = float(spot.get("ltp") or chain_resp.get("spot_price") or 0)
            if ltp > 0 and chain_resp.get("success"):
                underlying = {
                    "ltp": ltp,
                    "change_pct": float(spot.get("chg_pct") or spot.get("change_percent") or 0),
                    "vwap": derived.get("vwap") or ltp,
                    "ema20": derived.get("ema20_15") or ltp,
                    "vwap_dev_pct": 0.0,
                    "above_ema20": True,
                    "candles_5min": m15[-60:] if m15 else [],
                    "light": True,
                }
            else:
                underlying = {}

            if not chain_resp.get("success") or len(chain_resp.get("chain") or []) < 2:
                try:
                    live_chain = self.market_service.get_option_chain(symbol, strike_count)
                    if live_chain and live_chain.get("success") and len(live_chain.get("chain") or []) >= 2:
                        chain_resp = live_chain
                except Exception as exc:
                    logger.debug("get_symbol_flow live fetch fallback for %s failed: %s", symbol, exc)

            if live and (not chain_resp.get("success") or ltp <= 0):
                if getattr(self, "_scan_running", False):
                    live = False
                else:
                    underlying = self._get_underlying_data(symbol, light=True) or underlying
                    if not chain_resp.get("success"):
                        chain_resp = self.market_service.get_option_chain(symbol, strike_count)

            if not self._is_authenticated() and not chain_resp.get("success") and ltp <= 0:
                return {"success": False, "error": "Not authenticated", "flagged": []}

            spot = chain_resp.get("spot_price") or (underlying or {}).get("ltp") or ltp or 0
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

            stored_rep = ((snap.get("anomaly") or {}).get("report")) if isinstance(snap.get("anomaly"), dict) else None
            last = self.get_last_scan() or {}
            board_row = next(
                (
                    r
                    for r in (last.get("tradeable") or [])
                    + (last.get("flagged") or [])
                    + (last.get("watch") or [])
                    + (last.get("bullish") or [])
                    + (last.get("bearish") or [])
                    if r.get("symbol") == symbol
                ),
                None,
            )

            if not underlying or not underlying.get("ltp"):
                report = stored_rep or board_row
                if report:
                    px = float(report.get("spot") or 0)
                    return {
                        "success": True,
                        "engine": "v6-anomaly",
                        "symbol": symbol,
                        "name": _sym_name(symbol),
                        "report": stored_rep or report,
                        "trade": (stored_rep or report).get("trade"),
                        "anomalies": (stored_rep or {}).get("anomalies") or [],
                        "structure": (stored_rep or {}).get("structure") or {
                            "oi_pcr": report.get("oi_pcr"),
                            "call_wall": report.get("call_wall"),
                            "put_wall": report.get("put_wall"),
                            "gamma_wall": report.get("gamma_wall"),
                        },
                        "grade": (stored_rep or report).get("grade"),
                        "chain_bias": (stored_rep or report).get("chain_bias"),
                        "why_not": (stored_rep or report).get("why_not"),
                        "chain": (chain_resp.get("chain") if chain_resp else []) or [],
                        "spot_price": px,
                        "partial": True,
                        "timestamp": datetime.now().isoformat(),
                    }
                return {"success": False, "error": f"Failed to get data for {symbol}", "flagged": []}
            expiries = chain_resp.get("expiries", [])

            normalized_expiries = [
                e.get("expiry") or e.get("date") or str(e) if isinstance(e, dict) else str(e)
                for e in expiries
            ]

            from app.services.chain_desk import evaluate

            if stored_rep and stored_rep.get("grade") and len(chain_resp.get("chain") or []) < 2:
                report = stored_rep
            else:
                report = evaluate(symbol, chain_resp, name=_sym_name(symbol))
            st = report.get("structure") or {}
            raw_chain = chain_resp.get("chain", [])
            annotated_chain = []
            for r in raw_chain:
                rc = dict(r)
                call = dict(r.get("call") or {})
                put = dict(r.get("put") or {})

                c_oi_chg = derive_oi_change_pct(call)
                c_pr_chg = float(call.get("chg_pct") or call.get("chp") or 0)
                c_sig = classify_signal(c_oi_chg, c_pr_chg, opt_type="CE")
                call["signal"] = c_sig["label"]
                call["signal_icon"] = c_sig["icon"]
                call["signal_direction"] = c_sig["direction"]
                call["oi_change_pct"] = round(c_oi_chg, 2)

                p_oi_chg = derive_oi_change_pct(put)
                p_pr_chg = float(put.get("chg_pct") or put.get("chp") or 0)
                p_sig = classify_signal(p_oi_chg, p_pr_chg, opt_type="PE")
                put["signal"] = p_sig["label"]
                put["signal_icon"] = p_sig["icon"]
                put["signal_direction"] = p_sig["direction"]
                put["oi_change_pct"] = round(p_oi_chg, 2)

                rc["call"] = call
                rc["put"] = put
                annotated_chain.append(rc)

            return {
                "success": True,
                "engine": "v6-anomaly",
                "symbol": symbol,
                "name": _sym_name(symbol),
                "underlying": underlying,
                "chain": annotated_chain,
                "spot_price": underlying.get("ltp"),
                "pcr": st.get("oi_pcr") or chain_resp.get("pcr"),
                "india_vix": chain_resp.get("india_vix"),
                "atm_strike": chain_resp.get("atm_strike") or report.get("atm"),
                "expiries": normalized_expiries,
                "report": report,
                "trade": report.get("trade"),
                "anomalies": report.get("anomalies") or [],
                "structure": st,
                "futures": report.get("futures"),
                "htf": report.get("htf"),
                "why_not": report.get("why_not"),
                "grade": report.get("grade"),
                "chain_bias": report.get("chain_bias"),
                "candles_5min": underlying.get("candles_5min", []),
                "freshness": {
                    "spot": store.classify_freshness(symbol, "spot"),
                    "chain": store.classify_freshness(symbol, "chain"),
                    "history_15": store.classify_freshness(symbol, "history.15"),
                    "history_d": store.classify_freshness(symbol, "history.D"),
                    "spot_age": store.age(symbol, "spot"),
                    "chain_age": store.age(symbol, "chain"),
                    "history_15_age": store.age(symbol, "history.15"),
                },
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
