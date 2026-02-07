from app.core.config import get_settings
import base64
import json

def diagnose():
    settings = get_settings()
    print("--- Loaded Settings ---")
    print(f"App ID: {settings.fyers_app_id}")
    print(f"Secret Key: {settings.fyers_secret_key}")
    print(f"Redirect URI: {settings.fyers_redirect_uri}")
    print(f"Has Token: {bool(settings.fyers_access_token)}")
    
    auth_code = "eyJhcHBfaWQiOiJXRzg4UTQzU0k2IiwidXVpZCI6IjM5MTg5ZjA1NGFiMjQ0NTc4NTcxMDkzN2U2NWY0NWY3IiwiaXBBZGRyIjoiIiwibm9uY2UiOiIiLCJzY29wZSI6IiIsImRpc3BsYXlfbmFtZSI6IkZBQTE2NTE1Iiwib21zIjoiSzEiLCJoc21fa2V5IjoiMjVkMGExZWRkNWU5MDA5NDY4ZWFmMGUxZWU0YTYzODI3M2NiYmE3MTFiYTQ0MTlmNTAxYTJjNjEiLCJpc0RkcGlFbmFibGVkIjoiTiIsImlzTXRmRW5hYmxlZCI6Ik4iLCJhdWQiOiJbXCJkOjFcIixcImQ6MlwiLFwieDowXCIsXCJ4OjFcIixcIng6MlwiXSIsImV4cCI6MTc3MDQyMDU5MSwiaWF0IjoxNzcwMzkwNTkxLCJpc3MiOiJhcGkubG9naW4uZnllcnMuaW4iLCJuYmYiOjE3NzAzOTA1OTEsInN1YiI6ImF1dGhfY29kZSJ9"
    
    print("\n--- Auth Code Payload ---")
    try:
        # Add padding if needed
        missing_padding = len(auth_code) % 4
        if missing_padding:
            auth_code += '=' * (4 - missing_padding)
        
        decoded = base64.b64decode(auth_code).decode('utf-8')
        payload = json.loads(decoded)
        print(json.dumps(payload, indent=2))
        
        # Check mismatch
        if payload.get("app_id") not in settings.fyers_app_id:
            print(f"⚠️ App ID Mismatch: Code has {payload.get('app_id')}, Settings has {settings.fyers_app_id}")
            
    except Exception as e:
        print(f"Error decoding: {e}")

if __name__ == "__main__":
    diagnose()
