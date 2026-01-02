#!/usr/bin/env bash
set -e

echo "=============================================="
echo "🚀 Starting SmartOps ERP Simulator"
echo "=============================================="

# Load environment variables
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../env/local.env"

# Ensure runtime directory exists
mkdir -p "${RUNTIME_DATA_DIR}"

echo "🔧 ERP Simulator Port : ${ERP_SIMULATOR_PORT}"
echo "📂 Runtime Data Dir  : ${RUNTIME_DATA_DIR}"
echo "----------------------------------------------"

# Start ERP Simulator
exec ${PYTHON_BIN} apps/erp-simulator/app.py
