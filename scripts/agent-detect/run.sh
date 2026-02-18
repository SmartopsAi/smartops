#!/usr/bin/env bash
set -e

echo ""
echo "🚀 Starting SmartOps Agent-Detect (Anomaly Detection)"
echo ""

# ------------------------------------------------------------
# Resolve project root
# ------------------------------------------------------------
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "📁 Project root: $PROJECT_ROOT"

# ------------------------------------------------------------
# Enforce Python 3.11
# ------------------------------------------------------------
if ! command -v python3.11 >/dev/null 2>&1; then
  echo "❌ Python 3.11 not found."
  echo "👉 Install with: brew install python@3.11"
  exit 1
fi

PYTHON_BIN="$(command -v python3.11)"
echo "🐍 Using Python: $PYTHON_BIN"
$PYTHON_BIN --version

# ------------------------------------------------------------
# Virtual environment
# ------------------------------------------------------------
if [ ! -d ".venv" ]; then
  echo "📦 Creating virtual environment (.venv)..."
  $PYTHON_BIN -m venv .venv
fi

echo "⚡ Activating virtual environment..."
source .venv/bin/activate

# ------------------------------------------------------------
# Install dependencies
# ------------------------------------------------------------
echo "📥 Installing dependencies..."
pip install --upgrade pip
pip install -r apps/agent-detect/requirements.txt

# ------------------------------------------------------------
# Environment variables (safe defaults)
# ------------------------------------------------------------
export PYTHONPATH="$PROJECT_ROOT"
export SMARTOPS_ENV="dev"

# ------------------------------------------------------------
# Runtime mode (IMPORTANT)
# ------------------------------------------------------------
# Default = simulator
export PROFILE="${PROFILE:-simulator}"

# If running against Kubernetes / Odoo
if [[ "$PROFILE" == "odoo" ]]; then
  echo "🧭 Agent-Detect running in ODOO mode"
  # Use Prometheus instead of ERP simulator
  export PROMETHEUS_API="http://localhost/prometheus/api/v1/query"
else
  echo "🧭 Agent-Detect running in SIMULATOR mode"
fi


# Prometheus (change if needed)
export PROMETHEUS_URL="http://localhost:9090"

# Runtime data directory (CRITICAL)
export SMARTOPS_RUNTIME_DIR="$PROJECT_ROOT/data/runtime"

# ------------------------------------------------------------
# Start Agent-Detect
# ------------------------------------------------------------
echo ""
echo "▶️  Starting Agent-Detect (live anomaly detection)"
echo "📂 Runtime output: $SMARTOPS_RUNTIME_DIR"
echo "🛑 Stop with CTRL+C"
echo ""

python apps/agent-detect/app.py
