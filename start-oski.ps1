# Starts Osky: FastAPI backend (:8000) + React frontend (:5174).
# First run installs everything. Usage:  powershell -ExecutionPolicy Bypass -File .\start-oski.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }

if (-not (Test-Path ".venv")) {
    Write-Host "Creando entorno Python..."
    python -m venv .venv
    .\.venv\Scripts\python -m pip install --upgrade pip
    .\.venv\Scripts\python -m pip install -r backend\requirements-local.txt
}

if (-not (Test-Path "frontend\node_modules")) {
    Write-Host "Instalando dependencias del frontend..."
    Push-Location frontend; npm install; Pop-Location
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$PSScriptRoot'; .\.venv\Scripts\python -m uvicorn backend.app.main:app --reload --reload-dir backend --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$PSScriptRoot\frontend'; npm run dev"

Start-Sleep -Seconds 4
Start-Process "http://localhost:5174"
Write-Host "Osky: http://localhost:5174   API: http://localhost:8000/docs"
