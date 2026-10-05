# Build and run the live OptionGreek stack (Redis + API + UI).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "backend\.env")) {
    Copy-Item "backend\.env.example" "backend\.env"
    Write-Host "Created backend\.env — fill Fyers + LLM keys, then re-run." -ForegroundColor Yellow
    exit 1
}

docker compose up -d --build
Write-Host ""
Write-Host "UI     http://localhost:3000"
Write-Host "Watch  http://localhost:3000/watch"
Write-Host "API    http://localhost:8000/docs"
Write-Host "Logs   docker compose logs -f backend"
