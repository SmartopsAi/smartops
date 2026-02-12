#!/usr/bin/env bash
set -e

echo ""
echo "🚀 Starting SmartOps Policy Engine (Container-first mode)"
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
pip install -r apps/policy_engine/requirements.txt

# ------------------------------------------------------------
# Environment variables (safe defaults)
# ------------------------------------------------------------
export PYTHONPATH="$PROJECT_ROOT"
export SMARTOPS_ENV="dev"

# ------------------------------------------------------------
# Start Policy Engine
# ------------------------------------------------------------
echo ""
echo "▶️  Starting Policy Engine on port 8002"
echo "🔗 Health check: http://localhost:8002/healthz"
echo "📘 API base:     http://localhost:8002/v1/policy"
echo "🛑 Stop with CTRL+C"
echo ""

uvicorn apps.policy_engine.app:app \
  --host 0.0.0.0 \
  --port 8002 \
  --reload
