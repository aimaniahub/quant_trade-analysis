"""
Background Option Flow Radar scheduler.

Runs a lighter TOP-FNO scan during market hours and publishes high-LIS hits
to the signal bus. Results stay cached on OptionFlowRadarService for
confluence + UI.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.services.fno_stocks import filter_valid_symbols
from app.services.option_flow_radar import ALL_FNO_WATCHLIST, get_radar_service
from app.services.signal_bus import get_signal_bus
from app.services.rate_limiter import get_fyers_limiter
from app.utils.market_hours import is_market_open

logger = logging.getLogger(__name__)

# Full F&O book — scheduler is the only universe Fyers writer
SCHEDULE_SYMBOLS = filter_valid_symbols(list(ALL_FNO_WATCHLIST))
INTERVAL_OPEN_SECS = 180      # 3 min full-book harvest while open
INTERVAL_CLOSED_SECS = 180    # check again soon after open
MIN_LIS_PUBLISH = 65
STARTUP_DELAY_SECS = 5        # was 90 — book must warm at the open


class RadarScheduler:
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.radar = get_radar_service()
        self.bus = get_signal_bus()

    def get_status(self) -> dict:
        last = self.radar.get_last_scan() or {}
        return {
            "running": self._running,
            "market_open": is_market_open(),
            "symbols": len(SCHEDULE_SYMBOLS),
            "interval_open_secs": INTERVAL_OPEN_SECS,
            "scan_running": bool(last.get("scan_running")),
            "last_scan_age_seconds": last.get("cache_age_seconds"),
            "last_flagged": last.get("total_flagged"),
            "last_timestamp": last.get("timestamp"),
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

    async def run_once(self) -> dict:
        """Manual / scheduled full-book harvest."""
        if self.radar._scan_running:
            return {"success": False, "error": "Scan already running"}

        if not self.radar._is_authenticated():
            return {"success": False, "error": "Not authenticated"}

        result = await asyncio.to_thread(
            self.radar.scan_all,
            None,    # full ALL_FNO_WATCHLIST
            0,       # min_lis
            None,    # opt type
            14,      # canonical equity width (indices harvested at 20 inside store)
        )
        if result.get("success"):
            self._publish_hits(result.get("flagged") or [])
        return result

    def _publish_hits(self, flagged: list):
        for row in flagged:
            try:
                lis = float(row.get("lis") or 0)
                conviction = (row.get("conviction") or {}).get("level") or ""
                if lis < MIN_LIS_PUBLISH and conviction != "HIGH":
                    continue
                sig = row.get("signal") or {}
                label = sig.get("label") if isinstance(sig, dict) else str(sig or "flow")
                self.bus.publish(
                    source="radar",
                    message=(
                        f"LIS {lis:.0f} {row.get('symbol')} "
                        f"{row.get('strike')}{row.get('type')} — {label}"
                    ),
                    level="signal",
                    symbol=row.get("symbol"),
                    score=lis,
                    meta={
                        "strike": row.get("strike"),
                        "type": row.get("type"),
                        "scheduled": True,
                    },
                )
            except Exception as exc:
                logger.debug(f"radar publish fail: {exc}")

    async def _loop(self):
        await asyncio.sleep(STARTUP_DELAY_SECS)
        limiter = get_fyers_limiter()
        while self._running:
            try:
                if not is_market_open():
                    logger.info("[RadarScheduler] market closed – sleep")
                    await asyncio.sleep(INTERVAL_CLOSED_SECS)
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
                if result.get("success"):
                    logger.info(
                        f"[RadarScheduler] done – flagged={result.get('total_flagged')} "
                        f"scanned={result.get('scanned')}"
                    )
                else:
                    logger.warning(f"[RadarScheduler] scan failed: {result.get('error')}")

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
