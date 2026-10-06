from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.routes import health, market_data, option_chain, websocket, auth, mcp
from app.routes import ma_crossover as ma_crossover_routes
from app.routes import option_flow_radar as radar_routes
from app.routes import ai_chain as ai_chain_routes
from app.routes import confluence as confluence_routes
from app.routes import ma7200 as ma7200_routes
from app.routes import rsi as rsi_routes
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

    import os
    is_serverless = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
    radar_sched = None
    aggregator = None
    ws_mgr = None

    if is_serverless:
        print("[SERVERLESS] Running in serverless mode (Vercel) - background loops & persistent WebSockets disabled")
    else:
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

        async def _trade_watch_loop():
            await _asyncio.sleep(8)
            while True:
                try:
                    from app.services.trade_watch import tick
                    await _asyncio.to_thread(tick)
                except Exception as watch_exc:
                    print(f"[WATCH] tick: {watch_exc}")
                await _asyncio.sleep(30)

        _asyncio.create_task(_trade_watch_loop())
        print("[WATCH] paper desk loop started (09:23 entry / 3m mark)")

        try:
            from app.services.spot_stream import get_spot_stream
            get_spot_stream().start()
            print("[WS] spot stream starting (canonical F&O universe)")
        except Exception as e:
            print(f"[WS] spot stream skipped: {e}")

    try:
        from app.services.option_flow_radar import get_radar_service
        last = get_radar_service().get_last_scan()
        n = len((last or {}).get("flagged") or []) + len((last or {}).get("symbol_states") or [])
        print(f"[RADAR] hydrated last board rows={n}")
    except Exception as e:
        print(f"[RADAR] hydrate skipped: {e}")

    # History sweeper must NOT start at boot. It competes with the chain
    # harvest for Fyers RPM. Radar starts it after the first harvest ends.
    print("[HISTORY] sweeper idle until first harvest completes")

    yield

    # ── Shutdown ───────────────────────────────────────────────────────
    print(f"[STOP] Shutting down {settings.app_name}")
    if radar_sched is not None:
        try:
            await radar_sched.stop()
        except Exception:
            pass
    try:
        ma_svc = get_ma_crossover_service()
        if getattr(ma_svc, "_running", False):
            await ma_svc.stop()
    except Exception:
        pass
    try:
        from app.services.spot_stream import get_spot_stream
        get_spot_stream().stop()
    except Exception:
        pass
    try:
        from app.services.history_sweeper import get_history_sweeper
        get_history_sweeper().stop()
    except Exception:
        pass
    if aggregator is not None:
        try:
            aggregator.stop()
        except Exception:
            pass
    if ws_mgr is not None and aggregator is not None:
        try:
            ws_mgr.remove_subscriber("market_data", aggregator.on_tick)
            ws_mgr.stop_all()
        except Exception:
            pass
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
        allow_origin_regex=r"^https:\/\/.*\.vercel\.app$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Middleware: Stateless token extractor for serverless (Vercel) instances
    @app.middleware("http")
    async def extract_client_auth_middleware(request: Request, call_next):
        token = (
            request.headers.get("x-fyers-access-token")
            or request.headers.get("x-fyers-token")
            or request.cookies.get("fyers_access_token")
        )
        if not token:
            auth_header = request.headers.get("authorization") or ""
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()

        if token and token != "undefined" and token != "null" and len(token) > 10:
            from app.services.fyers_auth import get_auth_service
            auth = get_auth_service()
            auth.set_token(token)

        response = await call_next(request)
        return response
    
    # Root health endpoint for platform probes (Render, AWS, uptime monitors)
    @app.get("/health", tags=["Health"])
    async def root_health():
        return {"status": "healthy", "service": settings.app_name}
    
    # Include routers
    app.include_router(health.router, prefix=settings.api_prefix, tags=["Health"])
    app.include_router(auth.router, prefix=f"{settings.api_prefix}/auth", tags=["Authentication"])
    app.include_router(market_data.router, prefix=settings.api_prefix, tags=["Market Data"])
    app.include_router(option_chain.router, prefix=settings.api_prefix, tags=["Option Chain"])
    app.include_router(websocket.router, prefix=settings.api_prefix, tags=["WebSocket"])
    app.include_router(websocket.router, tags=["WebSocket Root"])
    app.include_router(ma_crossover_routes.router, prefix=settings.api_prefix, tags=["MA Crossover"])
    app.include_router(radar_routes.router, prefix=settings.api_prefix, tags=["Option Flow Radar"])
    from app.routes import nifty_quant as nifty_quant_routes
    app.include_router(nifty_quant_routes.router, prefix=settings.api_prefix, tags=["Nifty Quant"])
    app.include_router(ai_chain_routes.router, prefix=settings.api_prefix, tags=["AI + Chain"])
    from app.routes import trade_watch as trade_watch_routes
    app.include_router(trade_watch_routes.router, prefix=settings.api_prefix, tags=["Trade Watch"])
    app.include_router(confluence_routes.router, prefix=settings.api_prefix, tags=["Confluence"])
    app.include_router(mcp.router, prefix=settings.api_prefix, tags=["Agentic AI (MCP)"])
    
    # Strategies
    from app.routes import strategies
    app.include_router(strategies.router, prefix=settings.api_prefix, tags=["Strategies"])
    app.include_router(ma7200_routes.router, prefix=settings.api_prefix, tags=["MA 7/200 + OC"])
    app.include_router(rsi_routes.router, prefix=settings.api_prefix, tags=["RSI Desk"])
    
    return app


app = create_app()
