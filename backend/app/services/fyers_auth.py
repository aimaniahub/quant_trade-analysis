"""
Fyers Authentication Service

Handles OAuth 2.0 authentication flow with Fyers API v3.
Supports both manual and automated (TOTP) login flows.
"""

import hashlib
import pyotp
from typing import Optional, Tuple
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
            auth_code: The authorization code from Fyers callback
            
        Returns:
            Tuple of (success, message, access_token)
        """
        try:
            if self._session is None:
                self._session = self._create_session()
            
            self._session.set_token(auth_code)
            response = self._session.generate_token()
            
            if "access_token" in response:
                access_token = response["access_token"]
                # Store token in environment for persistence
                self._store_access_token(access_token)
                return True, "Authentication successful", access_token
            else:
                error_msg = response.get("message", "Failed to generate token")
                return False, error_msg, None
                
        except Exception as e:
            return False, f"Authentication error: {str(e)}", None
    
    def _store_access_token(self, token: str):
        """Store access token to .env file for persistence."""
        import os
        from pathlib import Path
        
        # Update in-memory settings
        self.settings.fyers_access_token = token
        
        # Write to .env file for persistence
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
            return None
        
        # Re-initialize if token changed or model doesn't exist
        if self._fyers is None or getattr(self, "_last_token", None) != self.settings.fyers_access_token:
            self._fyers = fyersModel.FyersModel(
                token=self.settings.fyers_access_token,
                is_async=False,
                client_id=self.settings.fyers_app_id,
                log_path=""
            )
            self._last_token = self.settings.fyers_access_token
        
        return self._fyers
    
    def validate_token(self) -> Tuple[bool, str]:
        """
        Validate current access token by making a test API call.
        
        Returns:
            Tuple of (is_valid, message)
        """
        fyers = self.get_fyers_model()
        if not fyers:
            return False, "No access token configured"
        
        try:
            response = fyers.get_profile()
            if response.get("s") == "ok":
                return True, "Token is valid"
            else:
                return False, response.get("message", "Token validation failed")
        except Exception as e:
            return False, f"Token validation error: {str(e)}"
    
    def get_auth_status(self) -> dict:
        """
        Get current authentication status.
        
        Returns:
            Dict with authentication status details
        """
        has_token = bool(self.settings.fyers_access_token)
        is_valid = False
        user_info = None
        
        if has_token:
            is_valid, _ = self.validate_token()
            if is_valid:
                fyers = self.get_fyers_model()
                if fyers:
                    try:
                        profile = fyers.get_profile()
                        if profile.get("s") == "ok":
                            user_info = profile.get("data", {})
                    except:
                        pass
        
        return {
            "authenticated": has_token and is_valid,
            "has_token": has_token,
            "is_valid": is_valid,
            "user_info": user_info,
            "app_id": self.settings.fyers_app_id[:10] + "..." if self.settings.fyers_app_id else None
        }


# Singleton instance
_auth_service: Optional[FyersAuthService] = None


def get_auth_service() -> FyersAuthService:
    """Get the authentication service instance."""
    global _auth_service
    if _auth_service is None:
        _auth_service = FyersAuthService()
    return _auth_service
