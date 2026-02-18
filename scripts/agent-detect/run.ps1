Write-Host ""
Write-Host "🚀 Starting SmartOps Agent-Detect (Anomaly Detection)"
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
pip install -r apps\agent-detect\requirements.txt

# ------------------------------------------------------------
# Environment variables
# ------------------------------------------------------------
$env:PYTHONPATH = "$PROJECT_ROOT"
$env:SMARTOPS_ENV = "dev"
$env:PROMETHEUS_URL = "http://localhost:9090"
$env:SMARTOPS_RUNTIME_DIR = "$PROJECT_ROOT\data\runtime"

# ------------------------------------------------------------
# Start Agent-Detect
# ------------------------------------------------------------
Write-Host ""
Write-Host "▶️  Starting Agent-Detect (live anomaly detection)"
Write-Host "📂 Runtime output:" $env:SMARTOPS_RUNTIME_DIR
Write-Host "🛑 Stop with CTRL+C"
Write-Host ""

python apps/agent-detect/app.py
