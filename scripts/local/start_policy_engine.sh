#!/usr/bin/env bash
set -e

echo "=============================================="
echo "🚀 Starting SmartOps Policy Engine"
echo "=============================================="

# Resolve script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load environment variables
source "${SCRIPT_DIR}/../env/local.env"

# Ensure Python virtual environment is active
if [[ -z "$VIRTUAL_ENV" ]]; then
  echo "⚠️  Python virtual environment not active."
  echo "👉 Activate it with: source .venv/bin/activate"
  exit 1
fi

# Ensure apps/ is on PYTHONPATH
export PYTHONPATH="${PROJECT_ROOT}/apps:${PYTHONPATH}"

echo "🔧 Policy Engine Port : ${POLICY_ENGINE_PORT}"
echo "📜 Policy Directory  : apps/policy_engine/policies"
echo "🐍 PYTHONPATH       : ${PROJECT_ROOT}/apps"
echo "----------------------------------------------"

# Start Policy Engine
exec ${PYTHON_BIN} -m uvicorn apps.policy_engine.app:app \
  --host 127.0.0.1 \
  --port ${POLICY_ENGINE_PORT} \
  --reload
