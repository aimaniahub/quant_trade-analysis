from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.routes import health, market_data, option_chain, websocket, auth, mcp


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    print(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    yield
    # Shutdown
    print(f"👋 Shutting down {settings.app_name}")


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
    app.include_router(mcp.router, prefix=settings.api_prefix, tags=["Agentic AI (MCP)"])
    
    # Strategies
    from app.routes import strategies
    app.include_router(strategies.router, prefix=settings.api_prefix, tags=["Strategies"])
    
    return app


app = create_app()
