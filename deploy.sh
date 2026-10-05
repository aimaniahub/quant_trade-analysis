#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "Created backend/.env — fill Fyers + LLM keys, then re-run."
  exit 1
fi

docker compose up -d --build
echo
echo "UI     http://localhost:3000"
echo "Watch  http://localhost:3000/watch"
echo "API    http://localhost:8000/docs"
echo "Logs   docker compose logs -f backend"
