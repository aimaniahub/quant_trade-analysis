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
    Force reload settings from .env file.
    """
    from app.core.config import reload_settings
    new_settings = reload_settings()
    auth_service.settings = new_settings
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
    
    After clicking login, Fyers redirects to google.com with auth_code in URL.
    Copy the auth_code parameter value and submit it here.
    
    Example URL: https://google.com/?s=ok&code=ey...&auth_code=eyXXXXX&state=optiongreek
    Copy the auth_code value and submit it.
    """
    try:
        body = await request.json()
        auth_code = body.get("auth_code")
        
        if not auth_code:
            raise HTTPException(status_code=400, detail="auth_code is required")
        
        success, message, token = auth_service.handle_callback(auth_code)
        
        if success:
            return {
                "status": "success",
                "message": message,
                "info": "Access token saved to .env file"
            }
        else:
            raise HTTPException(status_code=400, detail=message)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
