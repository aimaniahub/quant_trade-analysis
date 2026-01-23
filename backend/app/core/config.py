from pydantic_settings import BaseSettings
from typing import Optional, List
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
    
    # WebSocket Configuration
    ws_heartbeat_interval: int = 30  # seconds
    ws_reconnect_delay: int = 5  # seconds
    ws_max_subscriptions: int = 200  # Fyers limit
    
    # Trading Configuration
    max_trades_per_day: int = 2
    min_risk_reward_ratio: float = 1.0
    
    # Market Hours (IST)
    market_open_hour: int = 9
    market_open_minute: int = 15
    market_close_hour: int = 15
    market_close_minute: int = 30
    
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
