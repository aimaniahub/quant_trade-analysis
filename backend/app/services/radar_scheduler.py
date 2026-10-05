"""
Background Option Flow Radar scheduler.

Single harvest actor: scheduler and manual Scan share one scan_all.
Every pass has a ScanJob the UI can poll.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from app.services.fno_stocks import filter_valid_symbols
from app.services.option_flow_radar import ALL_FNO_WATCHLIST, get_radar_service
from app.services.signal_bus import get_signal_bus
from app.services.rate_limiter import get_fyers_limiter
from app.utils.market_hours import last_session_date, seconds_to_market_open, session_is_open

logger = logging.getLogger(__name__)

# Full F&O book — this actor is the only universe Fyers writer
SCHEDULE_SYMBOLS = filter_valid_symbols(list(ALL_FNO_WATCHLIST))
INTERVAL_OPEN_SECS = 180
INTERVAL_CLOSED_SECS = 180
MIN_LIS_PUBLISH = 65
STARTUP_DELAY_SECS = 5


class RadarScheduler:
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._start_lock = asyncio.Lock()
        self._active_task: Optional[asyncio.Task] = None
        self.radar = get_radar_service()
        self.bus = get_signal_bus()

    def get_status(self) -> dict:
        last = self.radar.get_last_scan() or {}
        from app.services.scan_jobs import get_scan_job_manager

        job = get_scan_job_manager().find_running("radar")
        return {
            "running": self._running,
            "market_open": session_is_open(),
            "session_open": session_is_open(),
            "symbols": len(SCHEDULE_SYMBOLS),
            "interval_open_secs": INTERVAL_OPEN_SECS,
            "scan_running": bool(last.get("scan_running") or (job is not None)),
            "job_id": job.id if job else None,
            "phase": last.get("phase"),
            "scanned": last.get("attempted") or last.get("scanned"),
            "ok_chain": last.get("ok_chain"),
            "total": last.get("universe_requested") or last.get("total") or len(SCHEDULE_SYMBOLS),
            "last_scan_age_seconds": last.get("cache_age_seconds"),
            "last_flagged": last.get("total_flagged"),
            "last_timestamp": last.get("timestamp"),
            "workers": (last.get("telemetry") or {}).get("workers"),
            "top_tier_elapsed_sec": (last.get("telemetry") or {}).get("top_tier_elapsed_sec"),
            "elapsed_sec": (last.get("telemetry") or {}).get("elapsed_sec"),
            "rpm_peak": (last.get("telemetry") or {}).get("rpm_peak"),
        }

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[RadarScheduler] started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[RadarScheduler] stopped")

    def _make_progress(self, job_id: str):
        from app.services.scan_jobs import get_scan_job_manager

        mgr = get_scan_job_manager()

        def _on_progress(scanned, total, symbol, flagged_row, err, status="ok", ms=0):
            job_obj = mgr.get(job_id)
            meta = dict((job_obj.meta if job_obj else {}) or {})
            log = list(meta.get("log") or [])
            short = (symbol or "?").replace("NSE:", "").replace("-EQ", "").replace("-INDEX", "")
            if status != "start":
                log.append({
                    "sym": short,
                    "status": status,
                    "ms": int(ms or 0),
                    "err": (str(err)[:80] if err else None),
                })
            meta["log"] = log[-28:]
            meta["heartbeat_at"] = time.time()
            meta["last_status"] = status
            meta["last_error"] = str(err)[:120] if err else None
            meta["last_ms"] = int(ms or 0)
            last = self.radar.get_last_scan() or {}
            if last.get("phase"):
                meta["phase"] = last.get("phase")
            if status in ("wait", "retry", "retry_hit", "retry_start"):
                meta["phase"] = "wait"
            mgr.set_current(job_id, symbol)
            mgr.update(
                job_id,
                completed=int(scanned or 0),
                results=list(last.get("flagged") or []),
                partial=bool(last.get("partial", True)),
                meta=meta,
            )
            if status in ("hit", "retry_hit", "skip") and symbol:
                mgr.clear_failed_symbol(job_id, symbol)
            if err and status not in ("start", "wait", "retry", "retry_start"):
                mgr.note_error_only(
                    job_id,
                    symbol or "?",
                    str(err),
                    rate_limited=("rate_limit" in str(err).lower() or str(err) == "timeout"),
                )

        return _on_progress

    def _finish_job(self, job_id: str, result: Dict[str, Any]) -> None:
        from app.services.scan_jobs import get_scan_job_manager

        mgr = get_scan_job_manager()
        if not result.get("success"):
            mgr.finish(
                job_id,
                status="failed",
                error_message=result.get("error", "Scan failed"),
            )
            return
        flagged = result.get("flagged") or []
        mgr.update(
            job_id,
            results=flagged,
            completed=int(result.get("attempted") or result.get("scanned") or 0),
            rate_limited_skips=int(result.get("rate_limited_skips") or 0),
            partial=bool(result.get("partial")),
        )
        mgr.finish(
            job_id,
            status="completed",
            extra_meta={
                "summary": {
                    "engine": result.get("engine"),
                    "scanned": result.get("scanned"),
                    "attempted": result.get("attempted"),
                    "ok_chain": result.get("ok_chain"),
                    "hits": result.get("hits"),
                    "universe_requested": result.get("universe_requested"),
                    "total_flagged": result.get("total_flagged"),
                    "partial": result.get("partial"),
                    "completion_pct": result.get("completion_pct"),
                    "market_hours": result.get("market_hours"),
                    "timestamp": result.get("timestamp"),
                    "flagged": flagged,
                    "tradeable": result.get("tradeable") or flagged,
                    "quiet_count": result.get("quiet_count") or 0,
                    "watch": result.get("watch") or [],
                    "flow": result.get("flow") or [],
                    "alert_box": result.get("alert_box") or [],
                    "ideas": result.get("ideas") or [],
                    "ideas_confirmed": result.get("ideas_confirmed") or [],
                    "ideas_bullish": result.get("ideas_bullish") or [],
                    "ideas_bearish": result.get("ideas_bearish") or [],
                    "ideas_pullbacks": result.get("ideas_pullbacks") or [],
                    "ideas_watch": result.get("ideas_watch") or [],
                    "ideas_conflict": result.get("ideas_conflict") or [],
                    "idea_counts": result.get("idea_counts") or {},
                    "grade_counts": result.get("grade_counts"),
                    "rules": result.get("rules"),
                    "errors": result.get("errors"),
                    "skipped": result.get("skipped") or [],
                    "symbol_states": result.get("symbol_states") or [],
                    "telemetry": result.get("telemetry") or {},
                    "rate_limited_skips": result.get("rate_limited_skips"),
                    "retry_attempted": result.get("retry_attempted") or 0,
                    "retry_recovered": result.get("retry_recovered") or 0,
                    "failed_remaining": result.get("failed_remaining") or [],
                }
            },
        )

    async def ensure_pass(
        self,
        *,
        source: str = "scheduler",
        min_lis: float = 0,
        option_type: Optional[str] = None,
        strike_count: int = 14,
    ) -> Dict[str, Any]:
        """Start one full-book harvest if idle. If running, reuse that job."""
        from app.services.scan_jobs import get_scan_job_manager

        mgr = get_scan_job_manager()
        async with self._start_lock:
            existing = mgr.find_running("radar")
            if existing:
                return {
                    "success": True,
                    "job_id": existing.id,
                    "status": "running",
                    "total": existing.total,
                    "reused": True,
                    "source": source,
                    "completed": existing.completed,
                    "completion_pct": existing.completion_pct,
                    "poll_url": f"/api/v1/radar/scan/jobs/{existing.id}",
                }
            if getattr(self.radar, "_scan_running", False):
                return {
                    "success": True,
                    "job_id": None,
                    "status": "running",
                    "total": len(SCHEDULE_SYMBOLS),
                    "reused": True,
                    "source": source,
                    "message": "Harvest already running",
                    "poll_url": "/api/v1/radar/last",
                }
            if not self.radar._is_authenticated():
                return {"success": False, "error": "Not authenticated", "status": "blocked"}

            job = mgr.create(
                kind="radar",
                total=len(SCHEDULE_SYMBOLS),
                label=f"option flow radar ({source})",
                meta={
                    "min_lis": min_lis,
                    "option_type": option_type,
                    "strike_count": strike_count,
                    "source": source,
                    "heartbeat_at": time.time(),
                    "phase": "quotes",
                },
                pending_symbols=list(SCHEDULE_SYMBOLS),
            )
            mgr.mark_running(job.id)
            on_progress = self._make_progress(job.id)

            async def _worker():
                try:
                    result = await asyncio.to_thread(
                        self.radar.scan_all,
                        None,
                        min_lis,
                        option_type,
                        strike_count,
                        on_progress,
                    )
                    self._finish_job(job.id, result)
                    if result.get("success"):
                        self._publish_hits(result.get("flagged") or [])
                except asyncio.CancelledError:
                    mgr.finish(job.id, status="cancelled", error_message="cancelled")
                    raise
                except Exception as exc:
                    logger.error("[RadarScheduler] harvest failed: %s", exc, exc_info=True)
                    mgr.finish(job.id, status="failed", error_message=str(exc))

            task = asyncio.create_task(_worker())
            mgr.register_task(job.id, task)
            self._active_task = task
            logger.info("[RadarScheduler] harvest started job=%s source=%s n=%s", job.id, source, len(SCHEDULE_SYMBOLS))
            return {
                "success": True,
                "job_id": job.id,
                "status": "running",
                "total": len(SCHEDULE_SYMBOLS),
                "reused": False,
                "source": source,
                "poll_url": f"/api/v1/radar/scan/jobs/{job.id}",
            }

    async def run_once(self) -> dict:
        """Scheduled full-book harvest — waits until the pass finishes."""
        started = await self.ensure_pass(source="scheduler")
        task = self._active_task
        if task and not task.done():
            try:
                await task
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("[RadarScheduler] wait harvest: %s", exc)
        last = self.radar.get_last_scan() or {}
        if last:
            return last
        return started

    def _publish_hits(self, flagged: list):
        for row in flagged:
            try:
                if row.get("grade") != "TRADEABLE" and not row.get("trade"):
                    continue
                trade = row.get("trade") or {}
                top = row.get("top_anomaly") or {}
                self.bus.publish(
                    source="radar",
                    message=(
                        f"[TRADEABLE {row.get('chain_bias')}] {row.get('name') or row.get('symbol')} "
                        f"{trade.get('action') or ''} {trade.get('strike') or ''} "
                        f"— {top.get('label') or row.get('regime') or ''}"
                    ),
                    level="signal",
                    symbol=row.get("symbol"),
                    score=float(top.get("oi_added") or 0),
                    meta={
                        "grade": row.get("grade"),
                        "bias": row.get("chain_bias"),
                        "strike": trade.get("strike"),
                        "scheduled": True,
                    },
                )
            except Exception as exc:
                logger.debug(f"radar publish fail: {exc}")

    def _pin_session_if_needed(self) -> None:
        """Once per session close, freeze the board so after-hours UI keeps last prints."""
        day = last_session_date().isoformat()
        if getattr(self, "_pinned_session_date", None) == day:
            return
        pinned = self.radar.pin_last_session()
        if pinned:
            self._pinned_session_date = day
            logger.info(
                "[RadarScheduler] pinned last_session date=%s rows=%s",
                day,
                len(pinned.get("tradeable") or pinned.get("flagged") or []),
            )

    async def _loop(self):
        await asyncio.sleep(STARTUP_DELAY_SECS)
        limiter = get_fyers_limiter()
        while self._running:
            try:
                if not session_is_open():
                    try:
                        self._pin_session_if_needed()
                    except Exception as pin_exc:
                        logger.debug("[RadarScheduler] pin last_session: %s", pin_exc)
                    wait = min(INTERVAL_CLOSED_SECS, max(30.0, seconds_to_market_open() or INTERVAL_CLOSED_SECS))
                    logger.info("[RadarScheduler] session closed – serve last session, sleep %.0fs", wait)
                    await asyncio.sleep(wait)
                    continue

                if not self.radar._is_authenticated():
                    logger.warning("[RadarScheduler] not authenticated – sleep 120s")
                    await asyncio.sleep(120)
                    continue

                if limiter.in_cooldown:
                    wait = limiter.cooldown_remaining
                    logger.warning(f"[RadarScheduler] rate-limit cooldown – sleep {wait:.0f}s")
                    await asyncio.sleep(max(wait, 10))
                    continue

                logger.info("[RadarScheduler] starting full-book harvest…")
                result = await self.run_once()
                if result.get("success") is False:
                    logger.warning(f"[RadarScheduler] scan failed: {result.get('error')}")
                else:
                    logger.info(
                        f"[RadarScheduler] done – flagged={result.get('total_flagged')} "
                        f"ok_chain={result.get('ok_chain')} attempted={result.get('attempted') or result.get('scanned')}"
                    )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"[RadarScheduler] error: {exc}", exc_info=True)

            await asyncio.sleep(INTERVAL_OPEN_SECS)


_scheduler: Optional[RadarScheduler] = None


def get_radar_scheduler() -> RadarScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = RadarScheduler()
    return _scheduler
