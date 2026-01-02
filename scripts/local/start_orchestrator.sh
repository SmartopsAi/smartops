#!/usr/bin/env bash
set -e

echo "=============================================="
echo "🚀 Starting SmartOps Orchestrator"
echo "=============================================="

# Resolve script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables
source "${SCRIPT_DIR}/../env/local.env"

# Ensure Python virtual environment is active
if [[ -z "$VIRTUAL_ENV" ]]; then
  echo "⚠️  Python virtual environment not active."
  echo "👉 Activate it with: source .venv/bin/activate"
  exit 1
fi

echo "🔧 Orchestrator Port : ${ORCHESTRATOR_PORT}"
echo "🔗 Policy Engine URL : ${POLICY_ENGINE_URL}"
echo "----------------------------------------------"

# Start Orchestrator (FastAPI + Uvicorn)
exec ${PYTHON_BIN} -m uvicorn apps.orchestrator.app:app \
  --host 127.0.0.1 \
  --port ${ORCHESTRATOR_PORT} \
  --reload
