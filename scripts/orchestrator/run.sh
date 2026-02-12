#!/usr/bin/env bash
set -e

echo ""
echo "🚀 Starting SmartOps Orchestrator (Container-first mode)"
echo ""

# --------------------------------------------------
# Resolve paths
# --------------------------------------------------
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
ORCH_DIR="$ROOT_DIR/apps/orchestrator"
ENV_FILE="$ROOT_DIR/scripts/env/local.env"
VENV_DIR="$ROOT_DIR/.venv"

echo "📁 Project root: $ROOT_DIR"

# --------------------------------------------------
# Load environment variables
# --------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  echo "❌ Missing env file: $ENV_FILE"
  exit 1
fi

echo "🔐 Loading environment variables..."
set -o allexport
source "$ENV_FILE"
set +o allexport

# --------------------------------------------------
# Verify Python
# --------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "❌ python3 not found. Install Python 3.11+"
  exit 1
fi

python3 --version

# --------------------------------------------------
# Virtual environment
# --------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
  echo "📦 Creating virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

echo "⚙️ Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# --------------------------------------------------
# Install dependencies
# --------------------------------------------------
echo "📥 Installing dependencies..."
pip install --upgrade pip >/dev/null
pip install -r "$ORCH_DIR/requirements.txt"

# --------------------------------------------------
# PYTHONPATH (absolute imports)
# --------------------------------------------------
export PYTHONPATH="$ROOT_DIR"

# --------------------------------------------------
# Start Orchestrator
# --------------------------------------------------
echo ""
echo "▶️  Starting Orchestrator on port $ORCHESTRATOR_PORT"
echo "🔗 Health check: http://localhost:$ORCHESTRATOR_PORT/healthz"
echo "🛑 Stop with CTRL+C"
echo ""

uvicorn apps.orchestrator.app:app \
  --host 0.0.0.0 \
  --port "$ORCHESTRATOR_PORT" \
  --reload
