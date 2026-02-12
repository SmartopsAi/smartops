#!/usr/bin/env bash
set -e

echo ""
echo "🧠 Starting SmartOps Agent-Diagnose (RCA Engine)"
echo ""

# --------------------------------------------------
# Resolve project root
# --------------------------------------------------
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP_DIR="$PROJECT_ROOT/apps/agent-diagnose"
VENV_DIR="$PROJECT_ROOT/.venv"

cd "$PROJECT_ROOT"
echo "📁 Project root: $PROJECT_ROOT"

# --------------------------------------------------
# Python (use existing venv, DO NOT recreate)
# --------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
  echo "❌ .venv not found. Create it first (ERP / Policy scripts do this)."
  exit 1
fi

source "$VENV_DIR/bin/activate"
PYTHON_BIN="$VENV_DIR/bin/python"

echo "🐍 Using Python: $PYTHON_BIN"
$PYTHON_BIN --version

# --------------------------------------------------
# Install dependencies (idempotent)
# --------------------------------------------------
echo "📥 Installing agent-diagnose dependencies..."
pip install -r "$APP_DIR/requirements.txt"

# --------------------------------------------------
# Environment
# --------------------------------------------------
export PYTHONPATH="$PROJECT_ROOT/apps:$PROJECT_ROOT"
export SMARTOPS_ENV="dev"

# Ensure runtime directory exists
mkdir -p "$PROJECT_ROOT/data/runtime"

echo ""
echo "▶️  Agent-Diagnose running (continuous RCA loop)"
echo "📂 Output: data/runtime/latest_rca.json"
echo "⏱️  Interval: every 10 seconds"
echo "🛑 Stop with CTRL+C"
echo ""

# --------------------------------------------------
# Runtime mode (IMPORTANT)
# --------------------------------------------------
export PROFILE="${PROFILE:-simulator}"

if [[ "$PROFILE" == "odoo" ]]; then
  echo "🧭 Agent-Diagnose running in ODOO mode (chaos disabled)"
else
  echo "🧭 Agent-Diagnose running in SIMULATOR mode"
fi


# --------------------------------------------------
# Run (FOREVER LOOP)
# --------------------------------------------------
exec "$PYTHON_BIN" "$APP_DIR/integrate_with_detect.py"
