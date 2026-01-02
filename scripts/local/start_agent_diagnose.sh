#!/usr/bin/env bash
set -e

echo "=============================================="
echo "🧩 Starting SmartOps Agent Diagnose (RCA)"
echo "=============================================="

# Resolve directories
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

# Ensure runtime directory exists
mkdir -p "${RUNTIME_DATA_DIR}"

echo "📂 Runtime Data Dir : ${RUNTIME_DATA_DIR}"
echo "🐍 PYTHONPATH      : ${PROJECT_ROOT}/apps"
echo "🔁 Mode            : RCA on anomaly"
echo "----------------------------------------------"

# Start Agent Diagnose
exec ${PYTHON_BIN} apps/agent-diagnose/integrate_with_detect.py
