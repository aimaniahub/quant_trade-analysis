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
        from app.services.rate_limiter import get_fyers_limiter
        lim = get_fyers_limiter()
        rate = {
            "in_cooldown": lim.in_cooldown,
            "cooldown_remaining": round(lim.cooldown_remaining, 1),
        }
    except Exception:
        pass

    return {
        "status": "ready" if fyers_ok else "degraded",
        "dependencies": {
            "fyers_api": "ok" if fyers_ok else "unauthenticated",
            "grok_api": "configured" if settings.grok_api_key else "not_configured",
            "mcp_trading": "enabled" if settings.mcp_trading_enabled else "disabled",
        },
        "authenticated": fyers_ok,
        "cache": cache_stats,
        "rate_limit": rate,
    }
