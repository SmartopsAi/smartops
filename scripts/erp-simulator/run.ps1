New-Item -ItemType Directory -Force -Path scripts/erp-simulator | Out-Null

@'
Write-Host ""
Write-Host "🚀 Starting SmartOps ERP Simulator (Container-first mode)"
Write-Host ""

$ROOT_DIR = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$APP_DIR  = Join-Path $ROOT_DIR "apps\erp-simulator"
$ENV_FILE = Join-Path $ROOT_DIR "scripts\env\local.env"
$VENV_DIR = Join-Path $ROOT_DIR ".venv"

# --------------------------------------------------
# Force Python 3.11
# --------------------------------------------------
$PYTHON311 = Get-Command python3.11 -ErrorAction SilentlyContinue

if (-not $PYTHON311) {
    Write-Host "❌ python3.11 not found. Install from https://www.python.org/downloads/release/python-311/"
    exit 1
}

Write-Host "📁 Project root: $ROOT_DIR"
Write-Host "🐍 Forcing Python: $($PYTHON311.Source)"

# --------------------------------------------------
# Load env file
# --------------------------------------------------
if (-not (Test-Path $ENV_FILE)) {
    Write-Host "❌ Missing env file: $ENV_FILE"
    exit 1
}

Get-Content $ENV_FILE | ForEach-Object {
    if ($_ -match "=" -and -not $_.StartsWith("#")) {
        $name, $value = $_ -split "=", 2
        [System.Environment]::SetEnvironmentVariable($name, $value)
    }
}

# --------------------------------------------------
# Recreate venv (hard force 3.11)
# --------------------------------------------------
if (Test-Path $VENV_DIR) {
    Write-Host "🧹 Removing existing virtualenv..."
    Remove-Item -Recurse -Force $VENV_DIR
}

Write-Host "📦 Creating virtualenv with Python 3.11..."
python3.11 -m virtualenv $VENV_DIR

$VENV_PY = Join-Path $VENV_DIR "Scripts\python.exe"

Write-Host "🐍 Venv Python:"
& $VENV_PY --version

# --------------------------------------------------
# Install deps
# --------------------------------------------------
& $VENV_PY -m pip install --upgrade pip
& $VENV_PY -m pip install -r (Join-Path $APP_DIR "requirements.txt")

# --------------------------------------------------
# Run app
# --------------------------------------------------
Set-Location $APP_DIR

if (-not $env:ERP_SIMULATOR_PORT) {
    $env:ERP_SIMULATOR_PORT = "8000"
}

Write-Host ""
Write-Host "▶️  Starting ERP Simulator on port $env:ERP_SIMULATOR_PORT"
Write-Host "🔗 Health check: http://localhost:$env:ERP_SIMULATOR_PORT/healthz"
Write-Host "📊 Metrics:      http://localhost:$env:ERP_SIMULATOR_PORT/metrics"
Write-Host "🛑 Stop with CTRL+C"
Write-Host ""

& $VENV_PY -m uvicorn app:create_app --factory --host 0.0.0.0 --port $env:ERP_SIMULATOR_PORT
'@ | Set-Content scripts/erp-simulator/run.ps1
