from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.routes import health, market_data, option_chain, websocket, auth, mcp
from app.routes import ma_crossover as ma_crossover_routes
from app.routes import option_flow_radar as radar_routes
from app.routes import confluence as confluence_routes
from app.routes import ma7200 as ma7200_routes
from app.services.candle_aggregator import get_candle_aggregator
from app.services.strategies.ma_crossover import get_ma_crossover_service
from app.services.fyers_websocket import get_websocket_manager
from app.services.radar_scheduler import get_radar_scheduler


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # ── Startup ────────────────────────────────────────────────────────
    print(f"[START] Starting {settings.app_name} v{settings.app_version}")

    # Optional Redis (jobs + L2 market cache). Falls back to memory if off/down.
    try:
        from app.services.redis_client import init_redis, status as redis_status
        from app.services.scan_jobs import get_scan_job_manager

        ok = init_redis()
        st = redis_status()
        print(
            f"[REDIS] enabled={st.get('enabled')} connected={st.get('connected')} "
            f"backend={st.get('backend')}"
            + (f" err={st.get('error')}" if st.get("error") else "")
        )
        if ok:
            orphans = get_scan_job_manager().recover_orphans()
            if orphans:
                print(f"[REDIS] recovered {orphans} orphaned scan job(s) → interrupted")
    except Exception as e:
        print(f"[REDIS] init skipped: {e}")

    # Candle aggregator (ticks) — old multi-TF MA crossover service is DISABLED
    # so it no longer burns Fyers quota. Use 7/200 MA + OC strategy instead.
    aggregator = get_candle_aggregator()
    aggregator.start()

    ws_mgr = get_websocket_manager()
    ws_mgr.add_subscriber("market_data", aggregator.on_tick)

    import asyncio as _asyncio
    radar_sched = get_radar_scheduler()
    # Intentionally NOT starting get_ma_crossover_service().start()
    print("[MA] Legacy multi-TF MA crossover auto-scan DISABLED (use /strategies/ma7200)")
    _asyncio.create_task(radar_sched.start())

    yield

    # ── Shutdown ───────────────────────────────────────────────────────
    print(f"[STOP] Shutting down {settings.app_name}")
    await radar_sched.stop()
    try:
        ma_svc = get_ma_crossover_service()
        if getattr(ma_svc, "_running", False):
            await ma_svc.stop()
    except Exception:
        pass
    aggregator.stop()
    ws_mgr.remove_subscriber("market_data", aggregator.on_tick)
    try:
        ws_mgr.stop_all()
    except Exception:
        pass
    try:
        from app.services.redis_client import close_redis
        close_redis()
    except Exception:
        pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        description="Real-Time Option Intelligence & Market Structure Engine",
        version=settings.app_version,
        lifespan=lifespan,
    )
    
    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(health.router, prefix=settings.api_prefix, tags=["Health"])
    app.include_router(auth.router, prefix=f"{settings.api_prefix}/auth", tags=["Authentication"])
    app.include_router(market_data.router, prefix=settings.api_prefix, tags=["Market Data"])
    app.include_router(option_chain.router, prefix=settings.api_prefix, tags=["Option Chain"])
    app.include_router(websocket.router, prefix=settings.api_prefix, tags=["WebSocket"])
    app.include_router(ma_crossover_routes.router, prefix=settings.api_prefix, tags=["MA Crossover"])
    app.include_router(radar_routes.router, prefix=settings.api_prefix, tags=["Option Flow Radar"])
    app.include_router(confluence_routes.router, prefix=settings.api_prefix, tags=["Confluence"])
    app.include_router(mcp.router, prefix=settings.api_prefix, tags=["Agentic AI (MCP)"])
    
    # Strategies
    from app.routes import strategies
    app.include_router(strategies.router, prefix=settings.api_prefix, tags=["Strategies"])
    app.include_router(ma7200_routes.router, prefix=settings.api_prefix, tags=["MA 7/200 + OC"])
    
    return app


app = create_app()
