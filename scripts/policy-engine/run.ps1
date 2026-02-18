Write-Host ""
Write-Host "🚀 Starting SmartOps Policy Engine (Container-first mode)"
Write-Host ""

# ------------------------------------------------------------
# Resolve project root
# ------------------------------------------------------------
$PROJECT_ROOT = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $PROJECT_ROOT

Write-Host "📁 Project root:" $PROJECT_ROOT

# ------------------------------------------------------------
# Enforce Python 3.11
# ------------------------------------------------------------
$PYTHON = Get-Command python3.11 -ErrorAction SilentlyContinue

if (-not $PYTHON) {
    Write-Host "❌ Python 3.11 not found."
    Write-Host "👉 Install from: https://www.python.org/downloads/release/python-311/"
    exit 1
}

Write-Host "🐍 Using Python:" $PYTHON.Source
& $PYTHON.Source --version

# ------------------------------------------------------------
# Virtual environment
# ------------------------------------------------------------
if (-not (Test-Path ".venv")) {
    Write-Host "📦 Creating virtual environment (.venv)..."
    & $PYTHON.Source -m venv .venv
}

Write-Host "⚡ Activating virtual environment..."
& .\.venv\Scripts\Activate.ps1

# ------------------------------------------------------------
# Install dependencies
# ------------------------------------------------------------
Write-Host "📥 Installing dependencies..."
pip install --upgrade pip
pip install -r apps\policy_engine\requirements.txt

# ------------------------------------------------------------
# Environment variables (safe defaults)
# ------------------------------------------------------------
$env:PYTHONPATH = "$PROJECT_ROOT"
$env:SMARTOPS_ENV = "dev"

# ------------------------------------------------------------
# Start Policy Engine
# ------------------------------------------------------------
Write-Host ""
Write-Host "▶️  Starting Policy Engine on port 8002"
Write-Host "🔗 Health check: http://localhost:8002/healthz"
Write-Host "📘 API base:     http://localhost:8002/v1/policy"
Write-Host "🛑 Stop with CTRL+C"
Write-Host ""

uvicorn apps.policy_engine.app:app `
  --host 0.0.0.0 `
  --port 8002 `
  --reload
