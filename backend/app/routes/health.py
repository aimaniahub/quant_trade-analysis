from fastapi import APIRouter

from app.core.config import get_settings
from app.services.fyers_auth import get_auth_service

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "OptionGreek API"
    }


@router.get("/ready")
async def readiness_check():
    """Readiness check endpoint — reflects real Fyers auth state."""
    settings = get_settings()
    auth = get_auth_service()
    auth_status = auth.get_auth_status()
    fyers_ok = bool(auth_status.get("authenticated") or auth_status.get("is_valid"))

    cache_stats = {}
    try:
        from app.services.market_cache import get_market_cache
        cache_stats = get_market_cache().stats()
    except Exception:
        pass

    rate = {}
    try:
        from app.services.rate_limiter import get_fyers_limiter, FYERS_RPM_LIMIT
        lim = get_fyers_limiter()
        rate = lim.stats()
        rate["in_cooldown"] = lim.in_cooldown
        rate["cooldown_remaining"] = round(lim.cooldown_remaining, 1)
        try:
            rate["limit"] = int(settings.fyers_rpm_limit or FYERS_RPM_LIMIT)
        except Exception:
            rate["limit"] = FYERS_RPM_LIMIT
    except Exception:
        pass

    radar = {}
    try:
        from app.services.radar_scheduler import get_radar_scheduler
        radar = get_radar_scheduler().get_status()
    except Exception as e:
        radar = {"error": str(e)}

    redis_stats = {}
    try:
        from app.services.redis_client import status as redis_status
        redis_stats = redis_status()
    except Exception as e:
        redis_stats = {"enabled": False, "connected": False, "error": str(e)}

    job_stats = {}
    try:
        from app.services.scan_jobs import get_scan_job_manager
        job_stats = get_scan_job_manager().stats()
    except Exception:
        pass

    redis_dep = "disabled"
    if redis_stats.get("enabled"):
        redis_dep = "ok" if redis_stats.get("connected") else "down"

    harvest = {}
    try:
        from app.services.symbol_store import status as store_status

        harvest = store_status()
    except Exception as e:
        harvest = {"error": str(e)}

    ws = {}
    try:
        from app.services.spot_stream import get_spot_stream
        ws = get_spot_stream().status()
    except Exception as e:
        ws = {"status": "error", "error": str(e)}

    hist = {}
    try:
        from app.services.history_sweeper import get_history_sweeper
        hist = get_history_sweeper().status()
    except Exception as e:
        hist = {"error": str(e)}

    fyers_state = {}
    try:
        from app.services.market_gateway import get_market_gateway
        fyers_state = get_market_gateway().stats()
    except Exception:
        fyers_state = {
            "state": "COOLDOWN" if rate.get("cooldown") else "HEALTHY",
            "rpm": rate.get("requests_last_minute", 0),
            "rpm_limit": rate.get("limit", 200),
            "429_count": rate.get("429_count", 0),
            "cooldown": bool(rate.get("cooldown")),
            "cooldown_remaining": rate.get("cooldown_remaining", 0),
        }

    redis_health = "disabled"
    if redis_stats.get("enabled"):
        redis_health = "healthy" if redis_stats.get("connected") else "degraded"

    ready = fyers_ok
    if redis_stats.get("enabled") and not redis_stats.get("connected"):
        ready = False

    last_age = radar.get("last_scan_age_seconds")
    radar_out = {
        **radar,
        "last_harvest_age": last_age,
        "running": bool(radar.get("scan_running") or radar.get("running")),
    }

    return {
        "status": "ready" if ready else "degraded",
        "dependencies": {
            "fyers_api": "ok" if fyers_ok else "unauthenticated",
            "grok_api": "configured" if settings.grok_api_key else "not_configured",
            "mcp_trading": "enabled" if settings.mcp_trading_enabled else "disabled",
            "redis": redis_dep,
        },
        "authenticated": fyers_ok,
        "cache": cache_stats,
        "rate_limit": rate,
        "radar": radar_out,
        "fyers": fyers_state,
        "websocket": ws,
        "history_sweeper": hist,
        "redis": {**redis_stats, "status": redis_health},
        "scan_jobs": job_stats,
        "harvest": harvest,
    }
