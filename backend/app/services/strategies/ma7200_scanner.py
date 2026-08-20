"""
15-Min 7/200 EMA Cross + Option Chain Confirmation

v2 (7_200_cross.md Phase 1):
  - Direct Fyers 15m history per F&O equity
  - Only FRESH crosses: last closed bar or one before (bars_ago 0 or 1)
  - FIRST valid 7/200 cross in last 15 calendar days (anti-sideways)
  - Volume ≥ 1.5× prior 10 bars
  - MA cross = candidate only; Analyze Chain = final decision
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

FAST_PERIOD = 7
SLOW_PERIOD = 200
VOL_LOOKBACK = 10
VOL_MULT = 1.5
MIN_CANDLES = SLOW_PERIOD + 5
HISTORY_DAYS = 40
# Space direct API calls (~2/sec)
PACE_SEC = 0.5

# Phase-1 product rules (7_200_cross.md)
# bars_ago 0 = latest closed candle is the cross bar (REST history has no forming bar)
# bars_ago 1 = one candle before latest = "2 candles away"
FRESH_BARS_AGO = (0, 1)
FIRST_CROSS_WINDOW_DAYS = 15
MAX_EXTENSION_FROM_200_PCT = 2.5  # soft reject chase


def _ema_series(closes: List[float], period: int) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < period:
        return out
    k = 2.0 / (period + 1)
    val = sum(closes[:period]) / period
    out[period - 1] = val
    for i in range(period, n):
        val = closes[i] * k + val * (1.0 - k)
        out[i] = val
    return out


def _body_strength(candle: Dict) -> float:
    o = float(candle.get("open") or 0)
    h = float(candle.get("high") or 0)
    l = float(candle.get("low") or 0)
    c = float(candle.get("close") or 0)
    return abs(c - o) / max(h - l, 1e-9)


def _is_session_edge(ts: Optional[int]) -> bool:
    if not ts:
        return False
    try:
        dt = datetime.fromtimestamp(int(ts), tz=IST)
        t = dt.hour * 60 + dt.minute
        if 9 * 60 + 15 <= t < 9 * 60 + 30:
            return True
        if 15 * 60 + 15 < t <= 15 * 60 + 30:
            return True
    except Exception:
        pass
    return False


def _bar_ts(candle: Dict) -> Optional[int]:
    ts = candle.get("timestamp")
    if ts is not None:
        try:
            return int(ts)
        except (TypeError, ValueError):
            pass
    dt = candle.get("datetime")
    if dt:
        try:
            return int(datetime.fromisoformat(str(dt).replace("Z", "+00:00")).timestamp())
        except Exception:
            pass
    return None


def _classify_cross_at(
    i: int,
    closes: List[float],
    volumes: List[float],
    ema7: List[Optional[float]],
    ema200: List[Optional[float]],
    candles: List[Dict],
    *,
    require_volume: bool,
    skip_session_edge: bool,
    vol_mult: float,
) -> Optional[Dict[str, Any]]:
    """Geometry + volume + session filters for bar index i."""
    if i < 1:
        return None
    e7p, e200p = ema7[i - 1], ema200[i - 1]
    e7, e200 = ema7[i], ema200[i]
    if None in (e7p, e200p, e7, e200):
        return None

    bull = e7p <= e200p and e7 > e200
    bear = e7p >= e200p and e7 < e200
    if not bull and not bear:
        return None

    close = closes[i]
    if bull and not (close > e7 and close > e200):
        return None
    if bear and not (close < e7 and close < e200):
        return None

    prev10 = volumes[max(0, i - VOL_LOOKBACK) : i]
    avg10 = sum(prev10) / max(len(prev10), 1) if prev10 else 0.0
    last3 = volumes[max(0, i - 2) : i + 1]
    avg3 = sum(last3) / max(len(last3), 1)
    vol_ratio = max(volumes[i], avg3) / max(avg10, 1.0)
    if require_volume and vol_ratio < vol_mult:
        return None

    candle = candles[i]
    ts = _bar_ts(candle)
    if skip_session_edge and _is_session_edge(ts):
        return None

    body = _body_strength(candle)
    if body < 0.12 and vol_ratio < 1.8:
        return None

    e200_f = float(e200)
    extension = abs(close - e200_f) / max(abs(e200_f), 1e-9) * 100.0

    return {
        "cross_type": "BULLISH" if bull else "BEARISH",
        "cross_index": i,
        "cross_time": candle.get("datetime")
        or (datetime.fromtimestamp(ts, tz=IST).isoformat() if ts else None),
        "cross_ts": ts,
        "ltp": close,
        "ema7": round(float(e7), 2),
        "ema200": round(e200_f, 2),
        "volume": volumes[i],
        "volume_avg10": round(avg10, 0),
        "volume_ratio": round(vol_ratio, 2),
        "volume_rising": i >= 2 and volumes[i] >= volumes[i - 1] * 0.95,
        "trend_15m": "Up" if bull else "Down",
        "body_strength": round(body, 2),
        "bars_ago": len(closes) - 1 - i,
        "extension_from_200_pct": round(extension, 3),
    }


def find_all_valid_crosses(
    candles: List[Dict],
    *,
    require_volume: bool = True,
    skip_session_edge: bool = False,
    vol_mult: float = VOL_MULT,
    since_ts: Optional[int] = None,
    fast_period: int = FAST_PERIOD,
    slow_period: int = SLOW_PERIOD,
) -> List[Dict[str, Any]]:
    """All valid fast/slow EMA crosses (optionally since timestamp)."""
    fast_period = int(fast_period)
    slow_period = int(slow_period)
    if fast_period < 2 or slow_period <= fast_period:
        return []
    min_bars = slow_period + 5
    if not candles or len(candles) < min_bars:
        return []
    closes = [float(c.get("close") or 0) for c in candles]
    volumes = [float(c.get("volume") or 0) for c in candles]
    ema_fast = _ema_series(closes, fast_period)
    ema_slow = _ema_series(closes, slow_period)
    out: List[Dict[str, Any]] = []
    for i in range(slow_period, len(closes)):
        c = _classify_cross_at(
            i,
            closes,
            volumes,
            ema_fast,
            ema_slow,
            candles,
            require_volume=require_volume,
            skip_session_edge=skip_session_edge,
            vol_mult=vol_mult,
        )
        if not c:
            continue
        if since_ts is not None:
            cts = c.get("cross_ts")
            if cts is None or int(cts) < since_ts:
                continue
        out.append(c)
    return out


def momentum_score(
    cross: Dict[str, Any],
    *,
    vol_mult: float = VOL_MULT,
) -> float:
    """0–100 ranking score (7_200_cross.md §9)."""
    # bars_ago can be 0 — do not use `or 99` (0 is falsy)
    _b = cross.get("bars_ago")
    bars = 99 if _b is None else int(_b)
    score = 40.0 if bars == 0 else 25.0 if bars == 1 else 10.0 if bars <= 3 else 0.0
    if cross.get("first_cross_in_15d") or cross.get("first_cross_in_window"):
        score += 30.0
    vr = float(cross.get("volume_ratio") or 0)
    score += min(20.0, max(0.0, (vr - float(vol_mult)) * 20.0))
    if cross.get("volume_rising"):
        score += 10.0
    ext = float(cross.get("extension_from_200_pct") or 0)
    if ext > 2.0:
        score -= 15.0
    return round(max(0.0, min(100.0, score)), 1)


def detect_7_200_cross(
    candles: List[Dict],
    *,
    lookback_crosses: int = 12,  # kept for API compat; freshness uses max_bars_ago
    require_volume: bool = True,
    skip_session_edge: bool = True,
    vol_mult: float = VOL_MULT,
    first_cross_window_days: int = FIRST_CROSS_WINDOW_DAYS,
    fast_period: int = FAST_PERIOD,
    slow_period: int = SLOW_PERIOD,
    max_bars_ago: int = 1,  # accept bars_ago 0..max_bars_ago
    now_ts: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Momentum detect (settings-aware):
      - latest valid cross must be bars_ago in 0..max_bars_ago
      - exactly one valid cross in last `first_cross_window_days` calendar days
      - EMA(fast) / EMA(slow) cross with volume ≥ vol_mult
    """
    fast_period = int(fast_period)
    slow_period = int(slow_period)
    max_bars_ago = max(0, min(int(max_bars_ago), 20))
    first_cross_window_days = max(1, min(int(first_cross_window_days), 90))
    vol_mult = max(0.5, min(float(vol_mult), 10.0))

    if fast_period < 2 or slow_period <= fast_period:
        return None
    min_bars = slow_period + 5
    if not candles or len(candles) < min_bars:
        return None

    fresh_ok = tuple(range(0, max_bars_ago + 1))

    now = now_ts
    if now is None:
        # Prefer last candle time as "now" for historical consistency
        last_ts = _bar_ts(candles[-1])
        now = last_ts if last_ts else int(datetime.now(tz=IST).timestamp())

    since_ts = int(now) - int(first_cross_window_days * 86400)

    # Count all valid crosses in window (volume required for "valid")
    crosses_win = find_all_valid_crosses(
        candles,
        require_volume=require_volume,
        skip_session_edge=False,  # count all structural crosses in window
        vol_mult=vol_mult,
        since_ts=since_ts,
        fast_period=fast_period,
        slow_period=slow_period,
    )

    if not crosses_win:
        return None

    # Strict: only ONE valid cross in window days
    if len(crosses_win) != 1:
        return None

    cross = crosses_win[0]
    # bars_ago can be 0 — do not use `or 99` (0 is falsy in Python)
    _b = cross.get("bars_ago")
    bars_ago = 99 if _b is None else int(_b)
    if bars_ago not in fresh_ok:
        return None

    # Session edge: apply to final candidate
    if skip_session_edge and _is_session_edge(cross.get("cross_ts")):
        return None

    # Soft: don't chase extreme extension
    ext = float(cross.get("extension_from_200_pct") or 0)
    if ext > MAX_EXTENSION_FROM_200_PCT:
        return None

    cross = dict(cross)
    cross["first_cross_in_15d"] = True  # legacy field name (window may differ)
    cross["first_cross_in_window"] = True
    cross["crosses_in_15d"] = 1
    cross["crosses_in_window"] = 1
    cross["freshness"] = "FRESH"
    cross["fresh_label"] = f"{bars_ago + 1} bar" if bars_ago + 1 == 1 else f"{bars_ago + 1} bars"
    cross["momentum_score"] = momentum_score(cross, vol_mult=vol_mult)
    cross["window_days"] = first_cross_window_days
    cross["fast_ma"] = fast_period
    cross["slow_ma"] = slow_period
    cross["vol_mult_used"] = vol_mult
    cross["max_bars_ago"] = max_bars_ago
    return cross


# Backward-compatible alias used in tests
def detect_momentum_first_cross(candles: List[Dict], **kwargs) -> Optional[Dict[str, Any]]:
    return detect_7_200_cross(candles, **kwargs)


class MA7200ScannerService:
    def __init__(self):
        from app.services.fyers_market import get_market_service
        from app.services.fno_intelligence import get_intelligence_engine
        from app.services.fno_stocks import filter_valid_symbols, get_fno_stocks, TOP_FNO_STOCKS

        self.market = get_market_service()
        self.intel = get_intelligence_engine()
        self._filter = filter_valid_symbols
        self._all = get_fno_stocks
        self._top = TOP_FNO_STOCKS

    def _symbol_list(self, source: str, limit: int) -> List[str]:
        if source == "top":
            return self._filter(list(self._top))[:limit]
        # full / shared → full equity F&O
        return self._filter(list(self._all(top_only=False)))[:limit]

    def _fetch_15m_direct(self, symbol: str, days: int = HISTORY_DAYS) -> Dict[str, Any]:
        """Read harvested 15m from the symbol store. No force_refresh storm."""
        from app.services import symbol_store as store

        candles = store.get_history(symbol, "15", min_bars=1, days=days)
        if candles:
            return {
                "success": True,
                "candles": candles,
                "count": len(candles),
                "source": "store",
            }
        # Missing book — do not hit Fyers; harvest will fill this name
        return {
            "success": False,
            "candles": [],
            "error": "15m book not harvested yet",
            "source": "store_miss",
        }

    def _pace(self, limiter) -> None:
        while limiter.in_cooldown:
            w = min(limiter.cooldown_remaining, 10.0)
            if w <= 0:
                break
            logger.info("[ma7200] waiting rate cooldown %.1fs", w)
            time.sleep(w)
        time.sleep(PACE_SEC)

    def scan_universe(
        self,
        *,
        limit: int = 200,
        lookback_crosses: int = 12,
        source: str = "full",
        history_days: int = HISTORY_DAYS,
        job_id: Optional[str] = None,
        fast_ma: int = FAST_PERIOD,
        slow_ma: int = SLOW_PERIOD,
        window_days: int = FIRST_CROSS_WINDOW_DAYS,
        vol_mult: float = VOL_MULT,
        max_bars_ago: int = 1,
    ) -> Dict[str, Any]:
        """
        Direct API scan: one 15m history request per F&O symbol, then filter crosses.
        Optional job_id streams progress into ScanJobManager.
        Filter knobs: fast_ma, slow_ma, window_days, vol_mult, max_bars_ago.
        """
        from app.services.rate_limiter import get_fyers_limiter, is_rate_limit_error

        fast_ma = max(2, min(int(fast_ma), 100))
        slow_ma = max(fast_ma + 1, min(int(slow_ma), 500))
        window_days = max(1, min(int(window_days), 90))
        vol_mult = max(0.5, min(float(vol_mult), 10.0))
        max_bars_ago = max(0, min(int(max_bars_ago), 20))
        # Need enough history for slow EMA (+ buffer). ~25 bars/session day on 15m.
        min_hist = max(HISTORY_DAYS, int((slow_ma + 30) / 20) + 5, window_days + 5)
        history_days = max(int(history_days or HISTORY_DAYS), min_hist)
        history_days = min(history_days, 120)
        min_bars = slow_ma + 5

        symbols = self._symbol_list(source if source in ("top", "full", "shared") else "full", limit)
        limiter = get_fyers_limiter()
        mgr = None
        if job_id:
            from app.services.scan_jobs import get_scan_job_manager
            mgr = get_scan_job_manager()
            mgr.update(job_id, total=len(symbols), status="running")

        candidates: List[Dict[str, Any]] = []
        errors: List[Dict[str, str]] = []
        scanned = 0
        api_ok = 0
        api_fail = 0

        for idx, sym in enumerate(symbols):
            if mgr and job_id:
                mgr.set_current(job_id, sym)
                mgr.update(
                    job_id,
                    completed=idx,
                    completion_pct=round(100.0 * idx / max(len(symbols), 1), 1),
                )

            try:
                hist = self._fetch_15m_direct(sym, days=history_days)

                if not hist.get("success"):
                    err = str(hist.get("error") or "history_failed")
                    errors.append({"symbol": sym, "error": err})
                    continue

                candles = hist.get("candles") or []
                api_ok += 1
                scanned += 1

                if len(candles) < min_bars:
                    errors.append(
                        {
                            "symbol": sym,
                            "error": f"insufficient bars {len(candles)}/{min_bars}",
                        }
                    )
                    continue

                # Detect 0–2 closed bars. Desk then applies the strict bar-2 rule.
                detect_age = max(int(max_bars_ago), 2)
                cross = detect_7_200_cross(
                    candles,
                    require_volume=True,
                    skip_session_edge=True,
                    vol_mult=vol_mult,
                    first_cross_window_days=window_days,
                    fast_period=fast_ma,
                    slow_period=slow_ma,
                    max_bars_ago=detect_age,
                )
                near = None
                if not cross:
                    from app.services.strategies.ma7200_desk import score_near_cross

                    near = score_near_cross(candles, fast=fast_ma, slow=slow_ma)
                if not cross and not near:
                    continue

                from app.services.strategies.ma7200_desk import enrich_candidate

                row = enrich_candidate(
                    sym,
                    candles=candles,
                    cross=cross,
                    near=near,
                    fast_ma=fast_ma,
                    slow_ma=slow_ma,
                )
                if not row:
                    continue
                row["fast_ma"] = fast_ma
                row["slow_ma"] = slow_ma
                row["window_days"] = window_days
                row["data_source"] = hist.get("source") or "store"
                candidates.append(row)
                if mgr and job_id:
                    mgr.append_result_raw(job_id, row)

            except Exception as e:
                api_fail += 1
                msg = str(e)
                if is_rate_limit_error(e):
                    limiter.trip_limit(msg)
                errors.append({"symbol": sym, "error": msg})
                logger.warning("[ma7200] %s: %s", sym, e)

        def _desk_key(x: Dict[str, Any]):
            board_r = {"TRADE": 0, "WATCH": 1, "REJECT": 2}.get(x.get("board") or "", 3)
            return (
                board_r,
                -(x.get("desk_score") or x.get("momentum_score") or 0),
                99 if x.get("bars_ago") is None else int(x["bars_ago"]),
                x.get("name") or "",
            )

        candidates.sort(key=_desk_key)
        trade = [c for c in candidates if c.get("board") == "TRADE"]
        watch = [c for c in candidates if c.get("board") == "WATCH"]
        reject = [c for c in candidates if c.get("board") == "REJECT"]

        harvest = {}
        try:
            from app.services.symbol_store import status as store_status

            harvest = store_status()
        except Exception:
            harvest = {}

        age_label = "age 0–1 bars; bar-2 only if ext≤1.2% and P≥70"
        result = {
            "success": True,
            "scanned": scanned,
            "universe": len(symbols),
            "count": len(trade) + len(watch),
            "candidates": trade + watch,
            "trade": trade,
            "watch": watch,
            "reject": reject,
            "counts": {
                "trade": len(trade),
                "watch": len(watch),
                "reject": len(reject),
                "near": sum(1 for c in candidates if c.get("kind") == "NEAR"),
                "waiting_harvest": sum(
                    1 for e in errors if "not harvested" in str(e.get("error") or "")
                ),
            },
            "harvest": {
                "symbols": harvest.get("symbols"),
                "history_15_fresh": harvest.get("history_15_fresh"),
                "freshest_age": harvest.get("freshest_age"),
                "redis": harvest.get("redis"),
            },
            "errors": errors[:40] if errors else None,
            "error_count": len(errors),
            "rules": {
                "fresh_bars_ago": list(range(0, max_bars_ago + 1)),
                "first_cross_window_days": window_days,
                "volume_mult": vol_mult,
                "fast_ma": fast_ma,
                "slow_ma": slow_ma,
                "max_bars_ago": max_bars_ago,
                "max_extension_pct": MAX_EXTENSION_FROM_200_PCT,
                "description": (
                    f"First {fast_ma}/{slow_ma} in {window_days}d · {age_label} · "
                    f"vol ≥ {vol_mult}× · 4H allowed_side hard gate · no max-pain"
                ),
                "mtf_hard_gate": True,
                "max_pain": False,
            },
            "api": {
                "mode": "store",
                "ok": api_ok,
                "fail": api_fail,
                "pace_sec": 0,
                "history_days": history_days,
                "in_cooldown": limiter.in_cooldown,
                "cooldown_remaining": round(limiter.cooldown_remaining, 1),
            },
            "params": {
                "fast_ma": fast_ma,
                "slow_ma": slow_ma,
                "ma_type": "EMA",
                "timeframe": "15",
                "volume_mult": vol_mult,
                "window_days": window_days,
                "max_bars_ago": max_bars_ago,
                "lookback_crosses": lookback_crosses,
                "source": source,
                "limit": limit,
            },
            "timestamp": datetime.now(tz=IST).isoformat(),
            "note": (
                f"Desk on harvest book. TRADE needs 4H allowed_side + OC/futures permission. "
                f"Bar-2 only if ext≤1.2% and P≥70. Max pain not used."
            ),
        }

        if mgr and job_id:
            mgr.set_results(job_id, candidates)
            mgr.update(
                job_id,
                completed=scanned,
                completion_pct=100.0,
                results=candidates,
            )
            mgr.finish(
                job_id,
                status="completed",
                extra_meta={"summary": result},
            )

        return result

    def confirm_with_option_chain(
        self,
        symbol: str,
        cross_type: str,
        *,
        strike_count: int = 14,
    ) -> Dict[str, Any]:
        """Desk evaluate on the harvest snapshot. No private Fyers walk."""
        from app.services.strategies.ma7200_desk import evaluate_symbol

        cross_type = (cross_type or "").upper()
        if cross_type not in ("BULLISH", "BEARISH"):
            return {"success": False, "error": "cross_type must be BULLISH or BEARISH"}

        hist = self._fetch_15m_direct(symbol, days=HISTORY_DAYS)
        candles = hist.get("candles") or []
        if not candles:
            return {
                "success": False,
                "error": hist.get("error") or "15m book not harvested yet",
                "symbol": symbol,
            }

        ev = evaluate_symbol(
            symbol,
            candles=candles,
            cross_type=cross_type,
            fast_ma=FAST_PERIOD,
            slow_ma=SLOW_PERIOD,
        )
        if not ev.get("success"):
            return ev

        board = ev.get("board")
        ticket = ev.get("ticket")
        if board == "TRADE" and ticket:
            status, result, decision = "CONFIRMED", "CONFIRMED", (
                "LONG SETUP VALID" if cross_type == "BULLISH" else "SHORT SETUP VALID"
            )
        elif board == "WATCH":
            status, result, decision = "WATCH", "NOT_CONFIRMED", "WATCH — no ticket"
        else:
            status, result, decision = ev.get("board") or "REJECT", "NOT_CONFIRMED", "AVOID"

        hits = ev.get("permission_hits") or []
        suggested = []
        if ticket and ticket.get("vehicle"):
            v = ticket["vehicle"]
            suggested = [
                {
                    "role": "Primary",
                    "strike": v.get("strike"),
                    "instrument": v.get("instrument"),
                    "structure": v.get("structure"),
                    "style": v.get("style"),
                    "why": v.get("why"),
                }
            ]

        return {
            "success": True,
            **ev,
            "spot": ev.get("ltp"),
            "atm": (ticket or {}).get("vehicle", {}).get("strike") or ev.get("ltp"),
            "result": result,
            "status": status,
            "decision": decision,
            "reason": ev.get("board_reason"),
            "rules_hit": hits,
            "rules_miss": ev.get("permission_miss") or [],
            "hits": len(hits),
            "required_hits": None,
            "primary_flow": (hits[0].get("detail") if hits else ev.get("buildup_note")),
            "secondary_flow": hits[1].get("detail") if len(hits) > 1 else None,
            "suggested_strikes": suggested,
            "ticket": ticket,
            "report": self._format_ticket_report(ev, status, decision),
        }

    def _format_ticket_report(self, ev: Dict[str, Any], status: str, decision: str) -> str:
        name = ev.get("name") or ""
        t = ev.get("ticket") or {}
        v = t.get("vehicle") or {}
        lines = [
            f"Stock: {name}",
            f"Cross: {ev.get('cross_type')} · {ev.get('fresh_label')} · board {ev.get('board')}",
            f"4H: {ev.get('h4_bias')} allowed={ev.get('mtf_allowed')} gate={ev.get('mtf_gate')}",
            f"ADX {ev.get('adx')} · P {ev.get('permission')} · T {ev.get('momentum_score')} · desk {ev.get('desk_score')}",
            f"Result: {status} — {ev.get('board_reason')}",
            f"Decision: {decision}",
        ]
        if t:
            lines += [
                f"Vehicle: {v.get('structure')} ({v.get('style')}) — {v.get('why')}",
                f"Entry: {t.get('entry')}",
                f"Stop: {t.get('stop')} ({t.get('stop_src')})",
                f"Target: {t.get('target1')} ({t.get('target1_src')})",
                f"R:R {t.get('rr')} · {t.get('time_stop')}",
                f"Invalid: {t.get('invalidation')}",
            ]
        return "\n".join(lines)


_svc: Optional[MA7200ScannerService] = None


def get_ma7200_scanner() -> MA7200ScannerService:
    global _svc
    if _svc is None:
        _svc = MA7200ScannerService()
    return _svc
