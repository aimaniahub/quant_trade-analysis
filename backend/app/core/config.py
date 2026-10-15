from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional, List, Union
from functools import lru_cache
import json


class Settings(BaseSettings):
    """Application configuration settings."""
    
    # Application
    app_name: str = "OptionGreek"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # API
    api_prefix: str = "/api/v1"
    
    # CORS
    cors_origins: List[str] = ["http://localhost:3000"]
    
    @field_validator("cors_origins", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v):
        if isinstance(v, str):
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        return v
    
    # Fyers API Configuration
    fyers_app_id: str = ""
    fyers_secret_key: str = ""
    fyers_redirect_uri: str = "http://localhost:8000/api/v1/auth/callback"
    fyers_access_token: Optional[str] = None
    
    # Fyers User Credentials (for automated login)
    fyers_user_id: str = ""
    fyers_pin: str = ""
    fyers_totp_secret: str = ""
    
    # Grok API (for news engine)
    grok_api_key: str = ""
    grok_api_url: str = "https://api.x.ai/v1"
    # Optional preferred model (fallback chain used if empty/fails)
    grok_model: str = "grok-3-mini"

    # OpenRouter (AI + Chain news ranker)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemma-4-31b-it:free"
    
    # WebSocket Configuration
    ws_heartbeat_interval: int = 30  # seconds
    ws_reconnect_delay: int = 5  # seconds
    ws_max_subscriptions: int = 200  # Fyers limit
    
    # Trading Configuration
    max_trades_per_day: int = 2
    min_risk_reward_ratio: float = 1.0
    # Kill-switch: order placement via MCP is disabled unless explicitly enabled
    mcp_trading_enabled: bool = False
    # Optional shared secret for write tools (header: X-MCP-API-KEY)
    mcp_api_key: str = ""
    
    # Market Hours (IST)
    market_open_hour: int = 9
    market_open_minute: int = 15
    market_close_hour: int = 15
    market_close_minute: int = 30
    allow_off_hours_scan: bool = False

    # Redis (Upstash Redis integration on Vercel or local fallback)
    redis_enabled: bool = True
    redis_url: str = "redis://localhost:6379/0"
    redis_prefix: str = "optiongreek"
    redis_job_ttl_seconds: int = 3600  # scan job retention
    redis_socket_timeout: float = 4.0
    redis_connect_timeout: float = 4.0
    # How often to flush large job payloads during a running scan
    redis_job_persist_interval: float = 1.5

    @field_validator("redis_url", mode="before")
    @classmethod
    def assemble_redis_url(cls, v):
        import os
        # Check explicit Upstash integration environment variables from Vercel
        candidates = [
            os.getenv("redisupstashfyers_REDIS_URL"),
            os.getenv("redisupstashfyers_KV_URL"),
            os.getenv("UPSTASH_REDIS_URL"),
            os.getenv("KV_URL"),
            os.getenv("REDIS_URL"),
        ]
        for c in candidates:
            if c and str(c).strip() and not str(c).strip().startswith("redis://localhost:6379"):
                return str(c).strip()
        for k, val in os.environ.items():
            if (k.endswith("_REDIS_URL") or k.endswith("_KV_URL")) and val and str(val).strip():
                return str(val).strip()
        return v or "redis://localhost:6379/0"

    @field_validator("redis_enabled", mode="before")
    @classmethod
    def assemble_redis_enabled(cls, v):
        import os
        has_remote = any(
            bool(os.getenv(k))
            for k in [
                "redisupstashfyers_REDIS_URL",
                "redisupstashfyers_KV_URL",
                "UPSTASH_REDIS_URL",
                "KV_URL",
            ]
        ) or any((k.endswith("_REDIS_URL") or k.endswith("_KV_URL")) and bool(val) for k, val in os.environ.items())
        if has_remote:
            return True
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return bool(v)

    # Harvest / Redis symbol store (one writer, many readers)
    harvest_interval_secs: int = 180
    harvest_oc_strikes: int = 14
    harvest_oc_strikes_index: int = 20
    harvest_history_15_days: int = 40
    harvest_history_d_days: int = 30
    harvest_oc_ttl_secs: int = 120
    harvest_quotes_ttl_secs: int = 15
    harvest_history_15_ttl_secs: int = 900
    stale_soft_secs: int = 90
    stale_hard_secs: int = 300
    symbol_store_ttl_secs: int = 14400
    # Last-session board/quotes: survive overnight + weekend until next open.
    session_snapshot_ttl_secs: int = 259200

    # Readers (UI / HTTP) must not escape to Fyers. Harvest thread is the writer.
    # FYERS_READER_ESCAPE=true is a debug hatch only.
    fyers_reader_escape: bool = False
    fyers_rpm_limit: int = 200
    # Phase 2 harvest pacing (concurrency hides RTT; do not raise RPS)
    harvest_chain_workers: int = 4
    harvest_chain_rps: float = 3.0
    harvest_symbol_timeout_secs: float = 8.0
    harvest_retry_backoff_secs: float = 1.5
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
    
    @property
    def fyers_client_id(self) -> str:
        """Get formatted client ID for Fyers API."""
        return self.fyers_app_id
    
    def get_access_token_formatted(self) -> Optional[str]:
        """Get access token in Fyers format: app_id:access_token."""
        if self.fyers_access_token:
            return f"{self.fyers_app_id}:{self.fyers_access_token}"
        return None


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get settings instance (cached)."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Force reload settings from environment."""
    global _settings
    _settings = Settings()
    return _settings
