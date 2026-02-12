Write-Host ""
Write-Host "🧠 Starting SmartOps Agent-Diagnose (RCA Engine)"
Write-Host ""

# --------------------------------------------------
# Resolve project root
# --------------------------------------------------
$PROJECT_ROOT = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$APP_DIR = Join-Path $PROJECT_ROOT "apps\agent-diagnose"
$VENV_DIR = Join-Path $PROJECT_ROOT ".venv"

Set-Location $PROJECT_ROOT
Write-Host "📁 Project root:" $PROJECT_ROOT

# --------------------------------------------------
# Python venv check
# --------------------------------------------------
if (-not (Test-Path $VENV_DIR)) {
    Write-Host "❌ .venv not found. Create it first."
    exit 1
}

$PYTHON = Join-Path $VENV_DIR "Scripts\python.exe"
& $PYTHON --version

# --------------------------------------------------
# Install dependencies
# --------------------------------------------------
Write-Host "📥 Installing agent-diagnose dependencies..."
pip install -r "$APP_DIR\requirements.txt"

# --------------------------------------------------
# Environment
# --------------------------------------------------
$env:PYTHONPATH = "$PROJECT_ROOT\apps;$PROJECT_ROOT"
$env:SMARTOPS_ENV = "dev"

# Ensure runtime dir
New-Item -ItemType Directory -Force `
  -Path "$PROJECT_ROOT\data\runtime" | Out-Null

Write-Host ""
Write-Host "▶️  Agent-Diagnose running (continuous RCA loop)"
Write-Host "📂 Output: data\runtime\latest_rca.json"
Write-Host "⏱️  Interval: every 10 seconds"
Write-Host "🛑 Stop with CTRL+C"
Write-Host ""

# --------------------------------------------------
# Run
# --------------------------------------------------
& $PYTHON "$APP_DIR\integrate_with_detect.py"
