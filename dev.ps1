# PowerShell script to start both Backend and Frontend

# Function to start a process in a new window
function Start-NewTerminal {
    param (
        [string]$Title,
        [string]$Directory,
        [string]$Command
    )
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$Directory'; `$Host.UI.RawUI.WindowTitle = '$Title'; $Command"
}

Write-Host "Starting OptionGreek Services..." -ForegroundColor Cyan

# Start Backend
Write-Host "-> Launching Backend (uvicorn)..." -ForegroundColor Yellow
$BackendCmd = "if (Test-Path 'venv\Scripts\activate.ps1') { . venv\Scripts\activate.ps1 }; uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
Start-NewTerminal -Title "OptionGreek Backend" -Directory "$PSScriptRoot\backend" -Command $BackendCmd

# Start Frontend
Write-Host "-> Launching Frontend (next dev)..." -ForegroundColor Yellow
$FrontendCmd = "npm run dev"
Start-NewTerminal -Title "OptionGreek Frontend" -Directory "$PSScriptRoot\frontend" -Command $FrontendCmd

Write-Host "Services are being started in separate windows." -ForegroundColor Green
Write-Host "Backend: http://localhost:8000/docs"
Write-Host "Frontend: http://localhost:3000"
