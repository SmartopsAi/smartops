# ================================
# SmartOps Orchestrator Runner
# ================================

$ErrorActionPreference = "Stop"

Write-Host "`n🚀 Starting SmartOps Orchestrator (Container-first mode)`n"

# -------------------------------------------------
# Resolve paths
# -------------------------------------------------
$ROOT = Resolve-Path "$PSScriptRoot\..\.."
$ORCH_DIR = "$ROOT\apps\orchestrator"
$ENV_FILE = "$ROOT\scripts\env\local.env"
$VENV_DIR = "$ROOT\.venv"

Write-Host "📁 Project root: $ROOT"

# -------------------------------------------------
# Load environment variables
# -------------------------------------------------
if (!(Test-Path $ENV_FILE)) {
    Write-Host "❌ Missing env file: $ENV_FILE"
    exit 1
}

Write-Host "🔐 Loading environment variables..."
Get-Content $ENV_FILE | ForEach-Object {
    if ($_ -and $_ -notmatch '^#') {
        $name, $value = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($name, $value)
    }
}

# -------------------------------------------------
# Verify Python
# -------------------------------------------------
Write-Host "🐍 Checking Python..."
$python = Get-Command python -ErrorAction SilentlyContinue

if (-not $python) {
    Write-Host "❌ Python not found. Install Python 3.11+"
    exit 1
}

python --version

# -------------------------------------------------
# Virtual environment
# -------------------------------------------------
if (!(Test-Path $VENV_DIR)) {
    Write-Host "📦 Creating virtual environment..."
    python -m venv $VENV_DIR
}

Write-Host "⚙️ Activating virtual environment..."
& "$VENV_DIR\Scripts\Activate.ps1"

# -------------------------------------------------
# Install dependencies
# -------------------------------------------------
Write-Host "📥 Installing dependencies..."
pip install --upgrade pip | Out-Null
pip install -r "$ORCH_DIR\requirements.txt"

# -------------------------------------------------
# PYTHONPATH (absolute imports)
# -------------------------------------------------
$env:PYTHONPATH = $ROOT

# -------------------------------------------------
# Start Orchestrator
# -------------------------------------------------
Write-Host "`n▶️  Starting Orchestrator on port $env:ORCHESTRATOR_PORT"
Write-Host "🔗 Health check: http://localhost:$env:ORCHESTRATOR_PORT/healthz"
Write-Host "🛑 Stop with CTRL+C`n"

uvicorn apps.orchestrator.app:app `
  --host 0.0.0.0 `
  --port $env:ORCHESTRATOR_PORT `
  --reload
