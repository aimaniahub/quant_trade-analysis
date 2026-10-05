# OptionGreek Deployment Architecture & Guide

OptionGreek consists of:
1. **FastAPI Backend**: Python 3.12, long-running asyncio harvest scheduler, Fyers WebSocket data stream, paper trading desk, and option analysis engine.
2. **Next.js Frontend**: Next.js 16 (App Router), React 19, real-time WebSockets, TailwindCSS, and quantitative trading terminals.
3. **Optional Cache**: Redis (for persistent market snapshot & scan job retention, gracefully falls back to in-memory/JSON if disabled).

---

## 🚀 Platform Suitability: Render vs. Vercel

| Platform Requirement | Render | Vercel | Verdict & Recommendation |
| :--- | :---: | :---: | :--- |
| **Backend (FastAPI)** | ✅ **Supported** (Web Service) | ❌ **Unsupported** (Serverless functions timeout, no background tasks, no persistent broker WebSockets) | **Backend MUST run on Render** (or equivalent persistent container host). |
| **Frontend (Next.js)** | ✅ **Supported** (Docker / Node) | ✅ **Best in Class** (Native Next.js edge CDN, zero-config, preview branches) | **Frontend can run on Vercel (Recommended) OR Render**. |

### 🏆 Recommended Setup:
- **Frontend on Vercel**: Lightning fast worldwide CDN, instant git pushes.
- **Backend on Render**: 24/7 persistent container running the market harvest loop, Fyers socket client, and API routes.

*(Alternatively, you can deploy both Backend and Frontend on Render using our included `render.yaml` Blueprint for a single-dashboard setup).*

---

## Path 1: Hybrid Deployment (Frontend on Vercel + Backend on Render)

### Step 1: Deploy Backend on Render
1. Go to [Render Dashboard](https://dashboard.render.com).
2. Click **New +** → **Web Service**.
3. Connect your GitHub repository.
4. Set the configuration:
   - **Name**: `optiongreek-backend`
   - **Region**: Singapore or nearest to NSE (India)
   - **Language**: `Docker`
   - **Dockerfile Path**: `./backend/Dockerfile`
   - **Docker Context**: `./backend`
   - **Instance Type**: `Starter` (recommended so background schedulers don't sleep)
   - **Health Check Path**: `/health`
5. Under **Environment Variables**, add:
   - `PYTHONUNBUFFERED`: `1`
   - `FYERS_APP_ID`: Your Fyers App ID (e.g. `XXXXXXX-100`)
   - `FYERS_SECRET_KEY`: Your Fyers Secret Key
   - `FYERS_REDIRECT_URI`: `https://<your-render-backend>.onrender.com/api/v1/auth/callback`
   - `FYERS_ACCESS_TOKEN`: Your initial Fyers token (or auto-login credentials below)
   - `FYERS_USER_ID`: Fyers Client ID (optional, for auto TOTP login)
   - `FYERS_PIN`: 4-digit PIN (optional)
   - `FYERS_TOTP_SECRET`: TOTP 32-char secret (optional)
   - `GROK_API_KEY`: (optional, for AI-chain news sentiment)
   - `OPENROUTER_API_KEY`: (optional, for news ranker)
   - `REDIS_ENABLED`: `false` (or set `true` with `REDIS_URL` if you attach a Redis instance)
6. Click **Deploy Web Service**.
7. Note your public backend URL: `https://optiongreek-backend.onrender.com`.

### Step 2: Deploy Frontend on Vercel
1. Go to [Vercel Dashboard](https://vercel.com/dashboard) and click **Add New** → **Project**.
2. Import your GitHub repository.
3. Configure project settings:
   - **Root Directory**: Click edit and select `frontend`.
   - **Framework Preset**: `Next.js` (auto-detected).
4. Under **Environment Variables**, add:
   - `NEXT_PUBLIC_API_URL`: `https://optiongreek-backend.onrender.com/api/v1`
   - `NEXT_PUBLIC_WS_URL`: `wss://optiongreek-backend.onrender.com/ws`
5. Click **Deploy**.
6. Done! Your Next.js frontend is live on Vercel and talks directly to your Render backend via secure HTTPS and WebSockets.

---

## Path 2: All-in-One on Render (Blueprint Deployment)

We have provided a ready-made `render.yaml` file in the repo root:
1. Go to [Render Blueprints](https://dashboard.render.com/blueprints).
2. Click **New Blueprint Instance**.
3. Select your repository. Render will automatically read `render.yaml` and provision:
   - `optiongreek-backend`
   - `optiongreek-frontend`
4. Fill in your Fyers credentials when prompted in the UI.
5. Click **Apply**. Both services will build and link together seamlessly.

---

## Path 3: Local / Self-Hosted VPS (Docker Compose)

To run the complete stack locally or on any cloud VPS (AWS, DigitalOcean, Hetzner):
```bash
# 1. Setup secrets
cp backend/.env.example backend/.env

# 2. Launch full stack
docker compose up -d --build
```
- **UI**: http://localhost:3000
- **Live Watch Terminal**: http://localhost:3000/watch
- **Backend API & Swagger Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

---

## 🔒 Crucial Rules for Production

1. **Strictly 1 Backend Replica**:
   The harvest writer, Fyers WebSocket tick aggregator, and radar scheduler run in-process. Do NOT scale backend service replicas > 1.
2. **CORS is Pre-Configured**:
   Backend automatically accepts requests from `localhost:3000` and all `*.vercel.app` domains out of the box. Custom domains can be added via `CORS_ORIGINS=https://yourdomain.com`.
3. **Fyers Session Renewal**:
   Fyers tokens expire daily at 06:00 AM IST. Either:
   - Provide `FYERS_USER_ID`, `FYERS_PIN`, and `FYERS_TOTP_SECRET` in backend env for hands-free automated token renewals, OR
   - Click **Connect Fyers** on the UI header once each morning to authenticate.
