#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

source "$PROJECT_ROOT/scripts/env/local.env"
source "$PROJECT_ROOT/.venv/bin/activate"

echo "▶ Dashboard using POLICY_ENGINE_URL=$POLICY_ENGINE_URL"

python apps/dashboard/app.py
