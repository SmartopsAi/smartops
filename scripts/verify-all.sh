#!/usr/bin/env bash
set -e

echo ""
echo "🔍 SmartOps – System Verification"
echo "================================="

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

failures=0

check() {
  local name="$1"
  local cmd="$2"

  printf "▶ %-25s : " "$name"
  if eval "$cmd" >/dev/null 2>&1; then
    echo "✅ OK"
  else
    echo "❌ FAIL"
    failures=$((failures+1))
  fi
}

echo ""
echo "🧠 Local services"
echo "-----------------"

check "ERP Simulator"      "curl -sf http://localhost:8000/healthz"
check "Policy Engine"      "curl -sf http://localhost:8002/healthz"
check "Orchestrator"       "curl -sf http://localhost:8001/healthz"
check "Dashboard"          "curl -sf http://localhost:5050"

echo ""
echo "📂 Runtime artifacts"
echo "--------------------"

check "latest_detection"   "test -f data/runtime/latest_detection.json"
check "latest_risk"        "test -f data/runtime/latest_risk.json"
check "latest_rca"         "test -f data/runtime/latest_rca.json"

echo ""
echo "☸️ Kubernetes (if available)"
echo "----------------------------"

if command -v kubectl >/dev/null 2>&1 && kubectl get ns smartops-dev >/dev/null 2>&1; then
  check "Odoo deployment" \
    "kubectl -n smartops-dev get deploy odoo-web >/dev/null"

  check "ERP Simulator deploy" \
    "kubectl -n smartops-dev get deploy smartops-erp-simulator >/dev/null"

  check "Prometheus" \
    "kubectl -n smartops-dev get pod | grep -q prometheus"

  check "Grafana" \
    "kubectl -n smartops-dev get pod | grep -q grafana"

  check "Tempo" \
    "kubectl -n smartops-dev get pod | grep -q tempo"

else
  echo "⚠️  Kubernetes not reachable – skipping K8s checks"
fi

echo ""
echo "📜 Process-level checks"
echo "----------------------"

check "Agent Detect running" \
  "ps aux | grep -v grep | grep -q 'apps/agent-detect/app.py'"

check "Agent Diagnose running" \
  "ps aux | grep -v grep | grep -q 'agent-diagnose/integrate_with_detect.py'"

echo ""
echo "================================="

if [ "$failures" -eq 0 ]; then
  echo "🎉 ALL SYSTEMS OPERATIONAL"
  exit 0
else
  echo "❌ $failures check(s) failed"
  exit 1
fi
