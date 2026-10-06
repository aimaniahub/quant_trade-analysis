"""
Fyers Authentication Service

Handles OAuth 2.0 authentication flow with Fyers API v3.
Supports both manual and automated (TOTP) login flows.
"""

import hashlib
import pyotp
from typing import Any, Optional, Tuple
from urllib.parse import urlencode, parse_qs, urlparse
import httpx

from fyers_apiv3 import fyersModel

from app.core.config import get_settings, reload_settings


class FyersAuthService:
    """Service for handling Fyers API authentication."""
    
    def __init__(self):
        self.settings = get_settings()
        self._session: Optional[fyersModel.SessionModel] = None
        self._fyers: Optional[fyersModel.FyersModel] = None
        self._last_token = None
        self._valid_cache: Optional[Tuple[bool, str, float]] = None  # is_valid, msg, expires
    
    def _create_session(self) -> fyersModel.SessionModel:
        """Create a new Fyers session model."""
        return fyersModel.SessionModel(
            client_id=self.settings.fyers_app_id,
            redirect_uri=self.settings.fyers_redirect_uri,
            response_type="code",
            state="optiongreek",
            secret_key=self.settings.fyers_secret_key,
            grant_type="authorization_code"
        )
    
    def get_login_url(self) -> str:
        """
        Generate Fyers OAuth login URL.
        
        Returns:
            str: The URL to redirect user for authentication
        """
        self._session = self._create_session()
        return self._session.generate_authcode()
    
    def handle_callback(self, auth_code: str) -> Tuple[bool, str, Optional[str]]:
        """
        Handle OAuth callback and generate access token.
        
        Args:
            auth_code: The authorization code from Fyers callback (or raw query string/URL)
            
        Returns:
            Tuple of (success, message, access_token)
        """
        try:
            if not auth_code:
                return False, "Missing auth_code", None

            auth_code = str(auth_code).strip()
            
            # If the user passed a full URL, extract auth_code parameter
            if "auth_code=" in auth_code or "http" in auth_code:
                from urllib.parse import urlparse, parse_qs
                try:
                    parsed = urlparse(auth_code)
                    qs = parse_qs(parsed.query)
                    if "auth_code" in qs:
                        auth_code = qs["auth_code"][0]
                    elif "code" in qs and qs["code"][0] != "200":
                        auth_code = qs["code"][0]
                except Exception:
                    pass

            session = self._create_session()
            session.set_token(auth_code)
            response = session.generate_token()
            
            if isinstance(response, dict) and "access_token" in response:
                access_token = response["access_token"]
                # Store token in memory, Redis, /tmp, and .env (if writable)
                self._store_access_token(access_token)
                return True, "Authentication successful", access_token
            else:
                error_msg = response.get("message", "Failed to generate token") if isinstance(response, dict) else str(response)
                return False, error_msg, None
                
        except Exception as e:
            return False, f"Authentication error: {str(e)}", None
    
    def set_token(self, token: str) -> None:
        """Set access token from client request context (serverless middleware)."""
        if not token:
            return
        token = token.strip()
        if token in ("undefined", "null") or len(token) < 10:
            return
        if self.settings.fyers_access_token != token:
            self._store_access_token(token)

    def _store_access_token(self, token: str):
        """Store access token in memory, Redis, /tmp cache, and .env (if writable)."""
        token = token.strip()
        self.settings.fyers_access_token = token
        self._fyers = None
        self._last_token = None
        self._valid_cache = None
        self._cached_profile = None

        # 1. Store in Redis / Upstash if configured (persists across serverless instances)
        try:
            from app.services.redis_client import is_redis_configured, set_json
            if is_redis_configured():
                set_json("auth:fyers_access_token", token, ttl=86400)
        except Exception:
            pass

        # 2. Store in temp directory (writable in serverless /tmp)
        try:
            import tempfile
            from pathlib import Path
            tmp_file = Path(tempfile.gettempdir()) / "fyers_access_token.txt"
            tmp_file.write_text(token)
        except Exception:
            pass

        # 3. Write to .env file for local dev persistence (safe against read-only FS)
        try:
            from pathlib import Path
            env_path = Path(__file__).parent.parent.parent / ".env"
            if env_path.exists():
                lines = env_path.read_text().splitlines()
                updated = False
                new_lines = []
                for line in lines:
                    if line.startswith("FYERS_ACCESS_TOKEN="):
                        new_lines.append(f"FYERS_ACCESS_TOKEN={token}")
                        updated = True
                    else:
                        new_lines.append(line)
                
                if not updated:
                    new_lines.append(f"FYERS_ACCESS_TOKEN={token}")
                
                env_path.write_text("\n".join(new_lines))
        except Exception:
            pass
    
    def generate_totp(self) -> Optional[str]:
        """
        Generate TOTP code for automated login.
        
        Returns:
            TOTP code if secret is configured, None otherwise
        """
        if not self.settings.fyers_totp_secret:
            return None
        
        totp = pyotp.TOTP(self.settings.fyers_totp_secret)
        return totp.now()
    
    def automated_login(self) -> Tuple[bool, str, Optional[str]]:
        """
        Perform automated login using TOTP.
        
        This is useful for daily token generation without manual intervention.
        Requires fyers_user_id, fyers_pin, and fyers_totp_secret to be configured.
        
        Returns:
            Tuple of (success, message, access_token)
        """
        if not all([
            self.settings.fyers_user_id,
            self.settings.fyers_pin,
            self.settings.fyers_totp_secret
        ]):
            return False, "Missing credentials for automated login", None
        
        try:
            from fyers_apiv3 import fyersModel
            
            # Step 1: Create session
            session = fyersModel.SessionModel(
                client_id=self.settings.fyers_app_id,
                redirect_uri=self.settings.fyers_redirect_uri,
                response_type="code",
                state="optiongreek",
                secret_key=self.settings.fyers_secret_key,
                grant_type="authorization_code"
            )
            
            # Step 2: Generate TOTP
            totp_code = self.generate_totp()
            if not totp_code:
                return False, "Failed to generate TOTP", None
            
            # Step 3: Automated login
            # Note: This requires the sync login flow
            # For full automation, you may need to use selenium or similar
            # The Fyers API doesn't provide a direct programmatic login
            
            # Alternative: Use the token if already available
            if self.settings.fyers_access_token:
                return True, "Using existing access token", self.settings.fyers_access_token
            
            return False, "Automated login requires manual OAuth flow first", None
            
        except Exception as e:
            return False, f"Automated login error: {str(e)}", None
    
    def get_fyers_model(self) -> Optional[fyersModel.FyersModel]:
        """
        Get initialized FyersModel for API calls.
        
        Returns:
            FyersModel if authenticated, None otherwise
        """
        if not self.settings.fyers_access_token:
            # 1. Check Redis if available (cross-instance Vercel persistence)
            try:
                from app.services.redis_client import is_redis_configured, get_json
                if is_redis_configured():
                    cached = get_json("auth:fyers_access_token")
                    if cached:
                        self.settings.fyers_access_token = str(cached).strip()
            except Exception:
                pass

            # 2. Check /tmp token cache (writable lambda instance storage)
            if not self.settings.fyers_access_token:
                try:
                    import tempfile
                    from pathlib import Path
                    tmp_file = Path(tempfile.gettempdir()) / "fyers_access_token.txt"
                    if tmp_file.exists():
                        t = tmp_file.read_text().strip()
                        if t:
                            self.settings.fyers_access_token = t
                except Exception:
                    pass

        if not self.settings.fyers_access_token:
            return None
        
        # Re-initialize if token changed or model doesn't exist
        if self._fyers is None or getattr(self, "_last_token", None) != self.settings.fyers_access_token:
            token_to_use = self.settings.fyers_access_token
            # FyersModel internally prepends client_id: to the token for the API header.
            # So we ensure we pass ONLY the raw auth token, stripping any 'APP_ID:' prefix.
            if token_to_use and ":" in token_to_use:
                token_to_use = token_to_use.split(":", 1)[1]
                
            import tempfile
            writable_temp = tempfile.gettempdir()
            try:
                self._fyers = fyersModel.FyersModel(
                    token=token_to_use,
                    is_async=False,
                    client_id=self.settings.fyers_app_id,
                    log_path=writable_temp
                )
                self._last_token = self.settings.fyers_access_token
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to initialize FyersModel: {e}")
                self._fyers = None
                return None
        
        return self._fyers
    
    def validate_token(self, force: bool = False) -> Tuple[bool, str]:
        """
        Validate current access token by making a test API call.
        Cached for 60s to avoid profile spam from UI polls.
        """
        import time
        now = time.time()
        if (
            not force
            and self._valid_cache is not None
            and self._valid_cache[2] > now
        ):
            return self._valid_cache[0], self._valid_cache[1]

        fyers = self.get_fyers_model()
        if not fyers:
            result = (False, "No access token configured")
            self._valid_cache = (*result, now + 15)
            return result
        
        try:
            response = fyers.get_profile()
            if response.get("s") == "ok":
                result = (True, "Token is valid")
                self._valid_cache = (*result, now + 60)
                # Keep user profile on the instance for status
                self._cached_profile = response.get("data", {})
                return result
            result = (False, response.get("message", "Token validation failed"))
            self._valid_cache = (*result, now + 20)
            return result
        except Exception as e:
            result = (False, f"Token validation error: {str(e)}")
            self._valid_cache = (*result, now + 20)
            return result
    
    def get_auth_status(self) -> dict:
        """
        Get current authentication status.
        """
        if not self.settings.fyers_access_token:
            self.get_fyers_model()
        has_token = bool(self.settings.fyers_access_token)
        is_valid = False
        user_info = getattr(self, "_cached_profile", None)
        
        if has_token:
            is_valid, _ = self.validate_token(force=False)
            if is_valid and not user_info:
                # One profile fetch if not cached with validation
                fyers = self.get_fyers_model()
                if fyers:
                    try:
                        profile = fyers.get_profile()
                        if profile.get("s") == "ok":
                            user_info = profile.get("data", {})
                            self._cached_profile = user_info
                    except Exception:
                        pass
        
        return {
            "authenticated": has_token and is_valid,
            "has_token": has_token,
            "is_valid": is_valid,
            "user_info": user_info,
            "app_id": self.settings.fyers_app_id[:10] + "..." if self.settings.fyers_app_id else None
        }

    def apply_reloaded_settings(self) -> None:
        """Refresh in-memory settings after .env token write / reload."""
        self.settings = get_settings()
        self._fyers = None
        self._last_token = None
        self._valid_cache = None
        self._cached_profile = None
        # Clear market cache so next calls use new auth context cleanly
        try:
            from app.services.market_cache import get_market_cache
            get_market_cache().clear()
        except Exception:
            pass
        try:
            from app.services.fyers_websocket import get_websocket_manager
            get_websocket_manager().refresh_settings()
        except Exception:
            pass


# Singleton instance
_auth_service: Optional[FyersAuthService] = None


def get_auth_service() -> FyersAuthService:
    """Get the authentication service instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = FyersAuthService()
    return _auth_service
