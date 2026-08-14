# OptionGreek

Real-time option intelligence for NSE F&O. The UI is the decision surface — every engine writes live Fyers data into the dashboard. No dummy market data.

## Stack

| Layer | Tech |
| :--- | :--- |
| Frontend | Next.js (React + TypeScript) |
| Backend | FastAPI (Python) |
| Live data | Fyers API v3 + WebSockets |
| Optional | Redis (durable scan jobs + cache), Grok (news bias) |

## UI ↔ engines

| Dashboard view | Backend |
| :--- | :--- |
| Home — market state, indices, option chain, confluence, alerts | `/market/*`, `/options/*`, `/confluence`, `/ws/*` |
| Quant Dashboard | live-trade-signal, Greeks heatmap, Nifty sentiment, process idea book |
| Stocks Option | F&O universe scan jobs |
| VAT Scanner | Value Adjustment Theory (`/strategies/vat/*`) |
| Trading | MCP tools + Fyers orders |
| 7/200 Cross | 15m MA cross + option-chain confirm |
| Flow Radar | process idea book, MTF, OI clusters, institutional levels, execution plan |
| High Vol | relative-volume scanner + bulk OC analysis |

## Run locally

```powershell
# Windows
.\dev.ps1
```

Or separately:

```powershell
# backend
cd backend
.\venv\Scripts\activate
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend
npm run dev
```

Open http://localhost:3000. Configure `backend/.env` from `backend/.env.example` (Fyers App ID, secret, redirect URI).

Optional Redis:

```powershell
docker compose up -d redis
```

Then set `REDIS_ENABLED=true` and `REDIS_URL=redis://localhost:6379/0` in `backend/.env`.

## Layout

```
backend/     FastAPI app (routes, services, strategies)
frontend/    Next.js UI
docs/        Specs, playbooks, architecture notes
```

## Production notes

- Fyers access tokens expire daily (~06:00 IST). Use `POST /api/v1/auth/auto-login` (TOTP) before the open, or paste the auth code from the UI.
- Do not commit `.env`, tokens, or `backend/app/data/`.
- Protect the API in production — there is no user-auth middleware on trading routes.
