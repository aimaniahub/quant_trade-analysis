"""
Vercel entrypoint wrapper for FastAPI application.
Exposes the ASGI app instance for Vercel Python runtime.
"""
from app.main import app

__all__ = ["app"]
