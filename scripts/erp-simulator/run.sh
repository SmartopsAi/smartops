#!/usr/bin/env bash
set -e

echo ""
echo "🚀 Starting SmartOps ERP Simulator"
echo ""

# --------------------------------------------------
# Resolve paths
# --------------------------------------------------
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
APP_DIR="$ROOT_DIR/apps/erp-simulator"
ENV_FILE="$ROOT_DIR/scripts/env/local.env"
VENV_DIR="$ROOT_DIR/.venv"

echo "📁 Project root: $ROOT_DIR"

# --------------------------------------------------
# Enforce Python 3.11 (system)
# --------------------------------------------------
if ! command -v python3.11 >/dev/null 2>&1; then
  echo "❌ Python 3.11 not found."
  echo "👉 Install with: brew install python@3.11"
  exit 1
fi

PYTHON311="$(command -v python3.11)"
echo "🐍 System Python: $PYTHON311"
"$PYTHON311" --version

# --------------------------------------------------
# Load environment variables
# --------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  echo "❌ Missing env file: $ENV_FILE"
  exit 1
fi

set -o allexport
source "$ENV_FILE"
set +o allexport

# --------------------------------------------------
# Activate shared virtual environment
# --------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
  echo "❌ Shared virtualenv not found at $VENV_DIR"
  echo "👉 Run Orchestrator first to create it"
  exit 1
fi

echo "⚙️ Activating shared virtual environment..."
source "$VENV_DIR/bin/activate"

VENV_PY="$(which python)"
echo "🐍 Venv Python: $("$VENV_PY" --version)"

# --------------------------------------------------
# Install dependencies
# --------------------------------------------------
echo "📥 Installing ERP Simulator dependencies..."
pip install --upgrade pip
pip install -r "$APP_DIR/requirements.txt"

# --------------------------------------------------
# Runtime environment
# --------------------------------------------------
export PYTHONPATH="$ROOT_DIR"
export PROFILE="${PROFILE:-simulator}"
export PORT="${ERP_SIMULATOR_PORT:-8000}"

# --------------------------------------------------
# Start ERP Simulator
# --------------------------------------------------
echo ""
echo "▶️  Starting ERP Simulator on port $PORT"
echo "🔗 Health check: http://localhost:$PORT/healthz"
echo "📊 Metrics:      http://localhost:$PORT/metrics"
echo "🛑 Stop with CTRL+C"
echo ""

exec "$VENV_PY" -m uvicorn apps.erp-simulator.app:app \
  --host 0.0.0.0 \
  --port "$PORT"
