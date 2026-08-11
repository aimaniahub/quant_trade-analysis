from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from typing import Optional

from app.services.fyers_auth import get_auth_service

router = APIRouter()
auth_service = get_auth_service()


@router.get("/login")
async def login():
    """
    Get Fyers login URL.
    Redirects user to Fyers OAuth page.
    """
    login_url = auth_service.get_login_url()
    return {"login_url": login_url}


@router.get("/callback")
async def callback(code: str = Query(...), state: Optional[str] = None):
    """
    OAuth callback handler.
    Exchanges auth code for access token.
    """
    success, message, token = auth_service.handle_callback(code)
    
    if success:
        # In a real app, you might redirect to a frontend success page
        return {
            "status": "success",
            "message": message,
            "access_token": "Token generated and stored" # Don't return the full token for security
        }
    else:
        raise HTTPException(status_code=400, detail=message)


@router.get("/status")
async def get_status():
    """
    Check current authentication status.
    """
    return auth_service.get_auth_status()


@router.post("/refresh")
async def refresh_token():
    """
    Refresh/validate the current token.
    """
    is_valid, message = auth_service.validate_token()
    return {"is_valid": is_valid, "message": message}


@router.post("/reload-settings")
async def reload_settings_endpoint():
    """
    Force reload settings from .env file and refresh auth/WS/market cache.
    """
    from app.core.config import reload_settings
    reload_settings()
    auth_service.apply_reloaded_settings()
    return {"status": "success", "message": "Settings reloaded from .env"}


@router.post("/auto-login")
async def auto_login():
    """
    Attempt automated login using TOTP (if configured).
    """
    success, message, _ = auth_service.automated_login()
    if success:
        return {"status": "success", "message": message}
    else:
        raise HTTPException(status_code=400, detail=message)


@router.post("/token")
async def submit_auth_code(request: Request):
    """
    Submit auth code manually to generate access token.
    
    After clicking login, Fyers redirects to a URL with auth_code parameter.
    You can paste EITHER:
    - Just the auth_code value (e.g., eyXXXXX...)
    - The full redirect URL (e.g., https://google.com/?s=ok&code=ey...&auth_code=eyXXXXX&state=optiongreek)
    
    The endpoint auto-extracts the auth_code from URLs, converts it to an
    access token, saves it to .env, and reloads settings.
    """
    try:
        body = await request.json()
        raw_input = body.get("auth_code", "").strip()
        
        if not raw_input:
            raise HTTPException(status_code=400, detail="auth_code is required")
        
        # Auto-extract auth_code from full redirect URL
        auth_code = _extract_auth_code(raw_input)
        
        success, message, token = auth_service.handle_callback(auth_code)
        
        if success:
            # Reload settings so the app picks up the new token immediately
            from app.core.config import reload_settings
            reload_settings()
            auth_service.apply_reloaded_settings()
            
            return {
                "status": "success",
                "message": message,
                "info": "Access token saved to .env and settings reloaded"
            }
        else:
            raise HTTPException(status_code=400, detail=message)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _extract_auth_code(raw_input: str) -> str:
    """
    Extract auth_code from raw input.
    
    Accepts either:
    - A plain auth_code string (returned as-is)
    - A full redirect URL containing auth_code parameter
    """
    from urllib.parse import urlparse, parse_qs
    
    # If it looks like a URL, try to extract auth_code param
    if raw_input.startswith("http://") or raw_input.startswith("https://"):
        try:
            parsed = urlparse(raw_input)
            params = parse_qs(parsed.query)
            if "auth_code" in params:
                return params["auth_code"][0]
            elif "code" in params:
                return params["code"][0]
        except Exception:
            pass
    
    # Otherwise treat the whole input as the auth_code
    return raw_input
