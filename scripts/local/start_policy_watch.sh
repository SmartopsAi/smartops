#!/usr/bin/env bash
set -e

echo "=============================================="
echo "📜 Starting SmartOps Policy Watcher"
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

echo "🐍 PYTHONPATH : ${PROJECT_ROOT}/apps"
echo "📂 Audit Log  : apps/policy_engine/audit/policy_decisions.jsonl"
echo "----------------------------------------------"

# Start Policy Watcher
exec ${PYTHON_BIN} -m apps.policy_engine.tools.watch_report
