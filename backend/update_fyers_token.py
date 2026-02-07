from app.services.fyers_auth import get_auth_service
import sys

def update_token(auth_code):
    from fyers_apiv3 import fyersModel
    from app.core.config import get_settings
    import os
    
    settings = get_settings()
    app_ids = [settings.fyers_app_id]
    if settings.fyers_app_id.endswith("-100"):
        app_ids.append(settings.fyers_app_id.replace("-100", ""))
    
    redirect_uris = [settings.fyers_redirect_uri, "http://localhost:8000/api/v1/auth/callback"]
    
    for app_id in app_ids:
        for redirect_uri in redirect_uris:
            print(f"\n--- Trying App ID: {app_id} | Redirect: {redirect_uri} ---")
            try:
                session = fyersModel.SessionModel(
                    client_id=app_id,
                    secret_key=settings.fyers_secret_key,
                    redirect_uri=redirect_uri,
                    response_type="code",
                    grant_type="authorization_code"
                )
                session.set_token(auth_code)
                response = session.generate_token()
                print(f"Response: {response}")
                
                if "access_token" in response:
                    token = response["access_token"]
                    print(f"✅ Success! Token generated.")
                    from app.services.fyers_auth import get_auth_service
                    auth_service = get_auth_service()
                    auth_service._store_access_token(token)
                    print(f"✅ Token saved to .env")
                    return
                else:
                    print(f"❌ Failed: {response.get('message', 'Unknown error')}")
            except Exception as e:
                print(f"Error: {e}")
    
    print("\n❌ Could not generate token with any combination. Please check your Secret Key in .env")

if __name__ == "__main__":
    # The auth code provided by user
    auth_code = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcHBfaWQiOiJXRzg4UTQzU0k2IiwidXVpZCI6ImIxN2FhYzk3NmNkYjRmNTFhYjdhNDYxZTRiZGQ1ODA2IiwiaXBBZGRyIjoiIiwibm9uY2UiOiIiLCJzY29wZSI6IiIsImRpc3BsYXlfbmFtZSI6IkZBQTE2NTE1Iiwib21zIjoiSzEiLCJoc21fa2V5IjoiMTQwODVjMTE3OTJlMjYxY2Q1MzczNjY0Y2Q1ZjEwZDEwMWU0OTFjNzBjZDFkNWYwYTk2OTFjNGEiLCJpc0RkcGlFbmFibGVkIjoiTiIsImlzTXRmRW5hYmxlZCI6Ik4iLCJhdWQiOiJbXCJkOjFcIixcImQ6MlwiLFwieDowXCIsXCJ4OjFcIixcIng6MlwiXSIsImV4cCI6MTc3MDQyMDk0NywiaWF0IjoxNzcwMzkwOTQ3LCJpc3MiOiJhcGkubG9naW4uZnllcnMuaW4iLCJuYmYiOjE3NzAzOTA5NDcsInN1YiI6ImF1dGhfY29kZSJ9.oBCoAzWQuDXoi-0HBjbhRxfqoLRacKxfSsC5Pyx5efY"
    
    update_token(auth_code)
