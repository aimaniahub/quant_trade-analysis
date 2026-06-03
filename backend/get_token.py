"""
Quick script: Paste Fyers redirect URL -> Get access token -> Save to .env
Usage: python get_token.py
"""
import os
from urllib.parse import urlparse, parse_qs
from dotenv import set_key, load_dotenv
from fyers_apiv3 import fyersModel

ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_PATH)

APP_ID = os.getenv("FYERS_APP_ID", "")
SECRET = os.getenv("FYERS_SECRET_KEY", "")
REDIRECT = os.getenv("FYERS_REDIRECT_URI", "https://google.com")

if not APP_ID or not SECRET:
    print("ERROR: FYERS_APP_ID or FYERS_SECRET_KEY missing in .env")
    exit(1)

print(f"App ID  : {APP_ID}")
print(f"Redirect: {REDIRECT}")
print()

raw = input("Paste redirect URL or auth_code: ").strip()

# Extract auth_code from URL if needed
if raw.startswith("http"):
    params = parse_qs(urlparse(raw).query)
    code = params.get("auth_code", params.get("code", [None]))[0]
    if not code:
        print("ERROR: Could not find auth_code in URL")
        exit(1)
    print(f"Extracted auth_code: {code[:30]}...")
else:
    code = raw

# Convert to access token
session = fyersModel.SessionModel(
    client_id=APP_ID,
    secret_key=SECRET,
    redirect_uri=REDIRECT,
    response_type="code",
    grant_type="authorization_code",
)
session.set_token(code)
resp = session.generate_token()

if resp.get("access_token"):
    token = resp['access_token']
    set_key(ENV_PATH, "FYERS_ACCESS_TOKEN", token)
    print()
    print("SUCCESS! Token saved to .env")
    print(f"Token: {token[:40]}...")
else:
    print(f"FAILED: {resp}")
