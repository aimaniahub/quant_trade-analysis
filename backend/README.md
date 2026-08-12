# OptionGreek Backend

## Setup

1. Create virtual environment:
```bash
python -m venv venv
```

2. Activate virtual environment:
- Windows: `venv\Scripts\activate`
- Linux/Mac: `source venv/bin/activate`

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
```

5. **Redis (recommended)** — durable scan jobs + shared market cache:

```bash
# from repo root (requires Docker Desktop running)
docker compose up -d redis
```

In `backend/.env`:
```env
REDIS_ENABLED=true
REDIS_URL=redis://localhost:6379/0
REDIS_PREFIX=optiongreek
REDIS_JOB_TTL_SECONDS=3600
```

If Redis is down or `REDIS_ENABLED=false`, the API still runs with **in-memory** jobs/cache (jobs lost on restart).

6. Run the development server:
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Redis what it stores

| Key pattern | Purpose | TTL |
|-------------|---------|-----|
| `{prefix}:job:{id}` | Full scan job (progress + results) | `REDIS_JOB_TTL_SECONDS` |
| `{prefix}:jobs:all` / `{prefix}:jobs:{kind}` | Job indexes (ZSET) | ~job TTL |
| `{prefix}:mkt:*` | L2 Fyers quote/OC/history cache | short (3–45s) |
| `{prefix}:radar:last_scan` | Last radar scan for confluence | 30 min |

Check: `GET /api/v1/ready` → `dependencies.redis`, `redis`, `scan_jobs`, `cache.l2_*`

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
