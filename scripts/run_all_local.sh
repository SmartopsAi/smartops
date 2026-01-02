#!/usr/bin/env bash
set -e

echo "================================================="
echo "🚀 SmartOps — Full System Startup (Local Mode)"
echo "================================================="

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/scripts/env/local.env"
VENV_ACTIVATE="${PROJECT_ROOT}/.venv/bin/activate"

if [[ ! -f "$VENV_ACTIVATE" ]]; then
  echo "❌ Virtual environment not found (.venv)"
  echo "👉 Create it first using Python 3.11"
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ local.env not found"
  exit 1
fi

echo "📂 Project Root : $PROJECT_ROOT"
echo "🐍 Virtual Env  : .venv"
echo "⚙️  Env File    : scripts/env/local.env"
echo "-------------------------------------------------"

launch() {
  local title="$1"
  local cmd="$2"

  osascript <<OSA
tell application "Terminal"
  activate
  do script "cd $PROJECT_ROOT && source $VENV_ACTIVATE && $cmd"
end tell
OSA
}

echo "▶ Starting ERP Simulator"
launch "ERP" "./scripts/local/start_erp.sh"
sleep 3

echo "▶ Starting Policy Engine"
launch "Policy Engine" "./scripts/local/start_policy_engine.sh"
sleep 3

echo "▶ Starting Orchestrator"
launch "Orchestrator" "./scripts/local/start_orchestrator.sh"
sleep 3

echo "▶ Starting Agent Detect"
launch "Agent Detect" "./scripts/local/start_agent_detect.sh"
sleep 3

echo "▶ Starting Agent Diagnose"
launch "Agent Diagnose" "./scripts/local/start_agent_diagnose.sh"
sleep 3

echo "▶ Starting Policy Watcher"
launch "Policy Watcher" "./scripts/local/start_policy_watch.sh"

echo "-------------------------------------------------"
echo "✅ SmartOps FULL SYSTEM STARTED"
echo "👉 Inject chaos to test closed-loop recovery"
echo "-------------------------------------------------"
