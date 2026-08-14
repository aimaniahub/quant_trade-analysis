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
        """Direct Fyers history call (cache may still absorb identical repeats)."""
        return self.market.get_historical_data(
            symbol, resolution="15", days=days, force_refresh=True
        )

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
                self._pace(limiter)
                hist = self._fetch_15m_direct(sym, days=history_days)

                if not hist.get("success"):
                    err = str(hist.get("error") or "history_failed")
                    api_fail += 1
                    if is_rate_limit_error(err):
                        limiter.trip_limit(err)
                        errors.append({"symbol": sym, "error": err})
                        # wait and retry once
                        self._pace(limiter)
                        hist = self._fetch_15m_direct(sym, days=history_days)
                        if not hist.get("success"):
                            errors.append({"symbol": sym, "error": hist.get("error") or err})
                            continue
                        api_fail -= 1
                    else:
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

                # Settings-driven: first-in-window + age ≤ max_bars_ago
                cross = detect_7_200_cross(
                    candles,
                    require_volume=True,
                    skip_session_edge=True,
                    vol_mult=vol_mult,
                    first_cross_window_days=window_days,
                    fast_period=fast_ma,
                    slow_period=slow_ma,
                    max_bars_ago=max_bars_ago,
                )
                if not cross:
                    continue

                name = sym.replace("NSE:", "").replace("-EQ", "")
                row = {
                    "symbol": sym,
                    "name": name,
                    "ltp": cross["ltp"],
                    "cross_type": cross["cross_type"],
                    "cross_time": cross["cross_time"],
                    "volume_ratio": cross["volume_ratio"],
                    "trend_15m": cross["trend_15m"],
                    "ema7": cross["ema7"],
                    "ema200": cross["ema200"],
                    "ema_fast": cross["ema7"],
                    "ema_slow": cross["ema200"],
                    "bars_ago": cross["bars_ago"],
                    "fresh_label": cross.get("fresh_label"),
                    "freshness": cross.get("freshness"),
                    "first_cross_in_15d": cross.get("first_cross_in_15d", True),
                    "crosses_in_15d": cross.get("crosses_in_15d", 1),
                    "extension_from_200_pct": cross.get("extension_from_200_pct"),
                    "momentum_score": cross.get("momentum_score"),
                    "body_strength": cross["body_strength"],
                    "volume_rising": cross["volume_rising"],
                    "fast_ma": fast_ma,
                    "slow_ma": slow_ma,
                    "window_days": window_days,
                    "data_source": "fyers_api",
                    "status": "CANDIDATE",
                }
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

        # Momentum first, then freshest (bars_ago 0 is valid — never use `or 99`)
        candidates.sort(
            key=lambda x: (
                -(x.get("momentum_score") or 0),
                99 if x.get("bars_ago") is None else int(x["bars_ago"]),
                x.get("name") or "",
            )
        )

        age_label = f"age ≤ {max_bars_ago + 1} closed 15m candles"
        result = {
            "success": True,
            "scanned": scanned,
            "universe": len(symbols),
            "count": len(candidates),
            "candidates": candidates,
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
                    f"Only first {fast_ma}/{slow_ma} EMA cross in {window_days} calendar days, "
                    f"{age_label}, volume ≥ {vol_mult}×"
                ),
            },
            "api": {
                "mode": "direct",
                "ok": api_ok,
                "fail": api_fail,
                "pace_sec": PACE_SEC,
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
                f"Direct Fyers 15m API. FIRST {fast_ma}/{slow_ma} cross in {window_days}d, "
                f"{age_label}, vol ≥{vol_mult}×. Candidates only — Analyze Chain to confirm."
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
        strike_count: int = 12,
    ) -> Dict[str, Any]:
        cross_type = (cross_type or "").upper()
        if cross_type not in ("BULLISH", "BEARISH"):
            return {"success": False, "error": "cross_type must be BULLISH or BEARISH"}

        chain_data = self.market.get_option_chain(symbol, strike_count)
        if not chain_data.get("success"):
            return {
                "success": False,
                "error": chain_data.get("error") or "Failed to fetch option chain",
                "symbol": symbol,
            }

        analysis = self.intel.get_analysis_summary(chain_data, bypass_time_check=True)
        if analysis.get("error"):
            return {"success": False, "error": analysis["error"], "symbol": symbol}

        deep = analysis.get("deep_analytics") or {}
        buildup = analysis.get("buildup") or deep.get("buildup") or {}
        pcr = deep.get("pcr") or {}
        max_pain = analysis.get("max_pain") or (deep.get("max_pain") or {}).get("max_pain")
        spot = float(analysis.get("spot_price") or chain_data.get("spot_price") or 0)
        atm = analysis.get("atm_strike") or chain_data.get("atm_strike")
        oi_pcr = float(
            pcr.get("oi_pcr") or analysis.get("oi_pcr") or analysis.get("pcr") or 1.0
        )
        band = buildup.get("atm_band") or []
        rules_hit: List[Dict[str, Any]] = []
        rules_miss: List[str] = []

        def _near(side: str, want: str, above: Optional[bool]) -> List[str]:
            hits = []
            for row in band:
                st = (row.get(side) or {}).get("state") or ""
                strike = row.get("strike")
                if want not in st:
                    continue
                if atm is not None and strike is not None:
                    if above is True and strike < atm:
                        continue
                    if above is False and strike > atm:
                        continue
                hits.append(f"{strike} {side[:2].upper()}: {st}")
            return hits

        if cross_type == "BULLISH":
            ce_lb = _near("call", "Long Buildup", True)
            for row in band:
                if row.get("is_atm") and "Long Buildup" in (
                    (row.get("call") or {}).get("state") or ""
                ):
                    ce_lb.append(f"{row.get('strike')} CE ATM Long Buildup")
            if ce_lb or (
                buildup.get("primary_state") == "Long Buildup"
                and buildup.get("bias") == "BULLISH"
            ):
                rules_hit.append(
                    {
                        "rule": "Call Long Buildup ATM/+OTM",
                        "detail": "; ".join(ce_lb[:3])
                        or buildup.get("note")
                        or "primary Long Buildup",
                    }
                )
            else:
                rules_miss.append("No Call Long Buildup at ATM/above")

            pe_w = [
                f"{row.get('strike')} PE: {(row.get('put') or {}).get('state')}"
                for row in band
                if row.get("strike") is not None
                and atm
                and row["strike"] <= atm
                and (
                    "Short Buildup" in ((row.get("put") or {}).get("state") or "")
                    or "Short Covering" in ((row.get("put") or {}).get("state") or "")
                )
            ]
            if pe_w or int(buildup.get("strong_short_pe") or 0) > 0:
                rules_hit.append(
                    {
                        "rule": "Put Writing / support ATM/below",
                        "detail": "; ".join(pe_w[:3]) or "PE short-side activity",
                    }
                )
            else:
                rules_miss.append("No Put writing/support ATM/below")

            if oi_pcr > 1.0 or str(pcr.get("regime") or "").startswith("PUT"):
                rules_hit.append(
                    {"rule": "OI PCR supportive", "detail": f"OI PCR {oi_pcr:.2f}"}
                )
            else:
                rules_miss.append(f"OI PCR {oi_pcr:.2f} not supportive")

            if max_pain and spot and float(max_pain) > spot:
                rules_hit.append(
                    {
                        "rule": "Max Pain above spot",
                        "detail": f"MP {max_pain} > {spot:.1f}",
                    }
                )
            else:
                rules_miss.append("Max Pain not above spot")

            atm_ce_rel = float(pcr.get("atm_ce_rel_vol") or 0)
            atm_ce_share = float(pcr.get("atm_ce_vol_share") or 0)
            if atm_ce_rel >= 1.3 or atm_ce_share >= 0.55:
                rules_hit.append(
                    {
                        "rule": "Strong Call volume ATM",
                        "detail": f"CE {atm_ce_rel:.1f}× share {atm_ce_share:.0%}",
                    }
                )
            else:
                rules_miss.append("ATM Call volume not dominant")

            opposite = buildup.get("primary_state") == "Short Buildup" or (
                int(buildup.get("strong_long_pe") or 0) >= 2
                and buildup.get("bias") == "BEARISH"
            )
        else:
            pe_lb = _near("put", "Long Buildup", False)
            for row in band:
                if row.get("is_atm") and "Long Buildup" in (
                    (row.get("put") or {}).get("state") or ""
                ):
                    pe_lb.append(f"{row.get('strike')} PE ATM Long Buildup")
            if pe_lb or buildup.get("bias") == "BEARISH":
                rules_hit.append(
                    {
                        "rule": "Put Long Buildup ATM/below",
                        "detail": "; ".join(pe_lb[:3])
                        or buildup.get("note")
                        or "bearish lean",
                    }
                )
            else:
                rules_miss.append("No Put Long Buildup ATM/below")

            ce_w = [
                f"{row.get('strike')} CE: {(row.get('call') or {}).get('state')}"
                for row in band
                if row.get("strike") is not None
                and atm
                and row["strike"] >= atm
                and "Short" in ((row.get("call") or {}).get("state") or "")
            ]
            if ce_w or int(buildup.get("strong_short_ce") or 0) > 0:
                rules_hit.append(
                    {
                        "rule": "Call Writing ATM/above",
                        "detail": "; ".join(ce_w[:3]) or "CE short buildup",
                    }
                )
            else:
                rules_miss.append("No Call writing ATM/above")

            if oi_pcr < 0.85 or str(pcr.get("regime") or "").startswith("CALL"):
                rules_hit.append(
                    {"rule": "OI PCR bearish zone", "detail": f"OI PCR {oi_pcr:.2f}"}
                )
            else:
                rules_miss.append(f"OI PCR {oi_pcr:.2f} not < 0.85")

            if max_pain and spot and float(max_pain) < spot:
                rules_hit.append(
                    {
                        "rule": "Max Pain below spot",
                        "detail": f"MP {max_pain} < {spot:.1f}",
                    }
                )
            else:
                rules_miss.append("Max Pain not below spot")

            atm_pe_rel = float(pcr.get("atm_pe_rel_vol") or 0)
            if atm_pe_rel >= 1.3 or float(pcr.get("atm_ce_vol_share") or 1) <= 0.45:
                rules_hit.append(
                    {
                        "rule": "Strong Put volume / Call writing ATM",
                        "detail": f"PE {atm_pe_rel:.1f}×",
                    }
                )
            else:
                rules_miss.append("ATM Put volume not strong")

            opposite = (
                buildup.get("primary_state") == "Long Buildup"
                and buildup.get("bias") == "BULLISH"
            )

        hits = len(rules_hit)
        if opposite and hits < 3:
            status, decision = "CONFLICT", "AVOID"
            reason = f"Conflict – opposite option flow ({buildup.get('primary_state')})"
            result = "NOT_CONFIRMED"
        elif hits >= 2:
            status = result = "CONFIRMED"
            decision = (
                "LONG SETUP VALID" if cross_type == "BULLISH" else "SHORT SETUP VALID"
            )
            reason = f"{hits}/5 confirmation rules met"
        else:
            status = result = "NOT_CONFIRMED"
            decision = "AVOID"
            reason = f"Only {hits}/5 rules met — need ≥2"

        suggested = (
            self._suggest_strikes(cross_type, spot, atm, band)
            if status == "CONFIRMED"
            else []
        )
        primary_flow = rules_hit[0]["detail"] if rules_hit else "—"
        secondary = rules_hit[1]["detail"] if len(rules_hit) > 1 else None

        return {
            "success": True,
            "symbol": symbol,
            "name": symbol.replace("NSE:", "").replace("-EQ", ""),
            "cross_type": cross_type,
            "spot": spot,
            "atm": atm,
            "result": result,
            "status": status,
            "decision": decision,
            "reason": reason,
            "rules_hit": rules_hit,
            "rules_miss": rules_miss,
            "hits": hits,
            "required_hits": 2,
            "primary_flow": primary_flow,
            "secondary_flow": secondary,
            "oi_pcr": round(oi_pcr, 3),
            "volume_pcr": pcr.get("volume_pcr"),
            "max_pain": max_pain,
            "buildup_state": buildup.get("primary_state"),
            "buildup_note": buildup.get("note"),
            "suggested_strikes": suggested,
            "put_wall": analysis.get("put_wall"),
            "call_wall": analysis.get("call_wall"),
            "timestamp": datetime.now(tz=IST).isoformat(),
            "report": self._format_report(
                symbol,
                cross_type,
                status,
                decision,
                reason,
                primary_flow,
                secondary,
                oi_pcr,
                suggested,
                hits,
            ),
        }

    def _suggest_strikes(
        self, cross_type: str, spot: float, atm: Any, band: List[Dict]
    ) -> List[Dict[str, Any]]:
        atm_f = float(atm or spot or 0)
        out: List[Dict[str, Any]] = []
        if cross_type == "BULLISH":
            aggressive = next(
                (
                    row.get("strike")
                    for row in sorted(band, key=lambda r: r.get("strike") or 0)
                    if row.get("strike") is not None and row["strike"] > atm_f
                ),
                None,
            )
            out.append(
                {
                    "role": "Primary",
                    "strike": atm_f,
                    "instrument": "CE",
                    "structure": f"{atm_f} CE",
                }
            )
            if aggressive:
                out.append(
                    {
                        "role": "Aggressive",
                        "strike": aggressive,
                        "instrument": "CE",
                        "structure": f"{aggressive} CE",
                    }
                )
            step = abs((aggressive or atm_f) - atm_f) or max(5.0, round(atm_f * 0.01))
            out.append(
                {
                    "role": "Defined Risk",
                    "strike": atm_f,
                    "instrument": "CE",
                    "structure": f"{atm_f}/{atm_f + step} Bull Call Spread",
                }
            )
        else:
            aggressive = next(
                (
                    row.get("strike")
                    for row in sorted(band, key=lambda r: -(r.get("strike") or 0))
                    if row.get("strike") is not None and row["strike"] < atm_f
                ),
                None,
            )
            out.append(
                {
                    "role": "Primary",
                    "strike": atm_f,
                    "instrument": "PE",
                    "structure": f"{atm_f} PE",
                }
            )
            if aggressive:
                out.append(
                    {
                        "role": "Aggressive",
                        "strike": aggressive,
                        "instrument": "PE",
                        "structure": f"{aggressive} PE",
                    }
                )
            step = abs(atm_f - (aggressive or atm_f)) or max(5.0, round(atm_f * 0.01))
            out.append(
                {
                    "role": "Defined Risk",
                    "strike": atm_f,
                    "instrument": "PE",
                    "structure": f"{atm_f}/{atm_f - step} Put Spread",
                }
            )
        return out

    def _format_report(
        self,
        symbol: str,
        cross_type: str,
        status: str,
        decision: str,
        reason: str,
        primary: str,
        secondary: Optional[str],
        oi_pcr: float,
        suggested: List[Dict],
        hits: int,
    ) -> str:
        name = symbol.replace("NSE:", "").replace("-EQ", "")
        lines = [
            f"Stock: {name}",
            f"Cross: {cross_type}",
            f"Option Chain Result: {status}",
            f"Rules met: {hits}/5 — {reason}",
        ]
        if status == "CONFIRMED":
            lines += [
                f"Primary Flow: {primary}",
                *([f"Secondary Flow: {secondary}"] if secondary else []),
                f"OI PCR: {oi_pcr:.2f}",
                f"Decision: {decision}",
                "Suggested Strikes:",
                *[f"  - {s['role']}: {s['structure']}" for s in suggested],
            ]
        else:
            lines += [f"Reason: {reason}", f"Decision: {decision}"]
        return "\n".join(lines)


_svc: Optional[MA7200ScannerService] = None


def get_ma7200_scanner() -> MA7200ScannerService:
    global _svc
    if _svc is None:
        _svc = MA7200ScannerService()
    return _svc
