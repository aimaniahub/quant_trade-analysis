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

from app.services.fno_stocks import TOP_FNO_STOCKS, FNO_INDICES, filter_valid_symbols
from app.services.option_flow_radar import get_radar_service
from app.services.signal_bus import get_signal_bus
from app.services.rate_limiter import get_fyers_limiter
from app.utils.market_hours import is_market_open

logger = logging.getLogger(__name__)

# Lighter universe for scheduled scans (speed / rate limits)
SCHEDULE_SYMBOLS = filter_valid_symbols(
    list(dict.fromkeys([*TOP_FNO_STOCKS, *FNO_INDICES]))
)
INTERVAL_OPEN_SECS = 600      # 10 min while market open (was 5 — rate limit friendly)
INTERVAL_CLOSED_SECS = 180    # check again soon after open
MIN_LIS_PUBLISH = 65


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
        """Manual / scheduled single pass over TOP symbols."""
        if self.radar._scan_running:
            return {"success": False, "error": "Scan already running"}

        if not self.radar._is_authenticated():
            return {"success": False, "error": "Not authenticated"}

        self.radar._scan_running = True
        try:
            result = await asyncio.to_thread(
                self.radar.scan_all,
                SCHEDULE_SYMBOLS,
                0,       # min_lis
                None,    # opt type
                10,      # strike_count — enough for ±10% OI clusters
            )
            if result.get("success"):
                self._publish_hits(result.get("flagged") or [])
            return result
        finally:
            self.radar._scan_running = False

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
        # Delay past MA startup scan so both don't stampede Fyers together
        await asyncio.sleep(90)
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

                logger.info("[RadarScheduler] starting scheduled TOP-FNO scan…")
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
