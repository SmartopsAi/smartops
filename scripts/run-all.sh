#!/usr/bin/env bash
set -euo pipefail

# ==========================================================
# SmartOps unified launcher (Simulator / Odoo)
# ==========================================================

# ---------- Defaults ----------
export PROFILE="${PROFILE:-simulator}"

# ---------- Project root ----------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ---------- Module commands ----------
CMD_ERP_SIM="./scripts/erp-simulator/run.sh"
CMD_AGENT_DETECT="./scripts/agent-detect/run.sh"
CMD_AGENT_DIAGNOSE="./scripts/agent-diagnose/run.sh"
CMD_POLICY_ENGINE="./scripts/policy-engine/run.sh"
CMD_ORCHESTRATOR="./scripts/orchestrator/run.sh"
CMD_DASHBOARD="./scripts/dashboard/run.sh"

# ---------- Kubernetes / Odoo ----------
K8S_NAMESPACE="${K8S_NAMESPACE:-smartops-dev}"
ODOO_LABEL_SELECTOR="${ODOO_LABEL_SELECTOR:-app=odoo-web}"

# ---------- Helpers ----------
bold() { printf "\033[1m%s\033[0m\n" "$*"; }
info() { printf "\033[36m[INFO]\033[0m %s\n" "$*"; }
warn() { printf "\033[33m[WARN]\033[0m %s\n" "$*"; }
err()  { printf "\033[31m[ERR]\033[0m %s\n" "$*"; }

exists() { command -v "$1" >/dev/null 2>&1; }

require_file() {
  local f="$1"
  [[ -f "$ROOT_DIR/$f" ]] || {
    err "Missing file: $ROOT_DIR/$f"
    exit 1
  }
}

# ---------- Kubernetes detection ----------
detect_k8s_ready() {
  exists kubectl || return 1
  kubectl version --client >/dev/null 2>&1 || return 1
  kubectl cluster-info >/dev/null 2>&1 || return 1
  return 0
}

detect_odoo_present() {
  detect_k8s_ready || return 1
  kubectl get ns "$K8S_NAMESPACE" >/dev/null 2>&1 || return 1

  local pods
  pods="$(kubectl -n "$K8S_NAMESPACE" get pods -l "$ODOO_LABEL_SELECTOR" --no-headers 2>/dev/null | wc -l | tr -d ' ')"
  [[ "${pods:-0}" -gt 0 ]]
}

# ---------- macOS Terminal tab opener ----------
open_tab_mac() {
  local title="$1"
  local command="$2"

  /usr/bin/osascript <<OSA
tell application "Terminal"
  activate
  tell application "System Events" to keystroke "t" using command down
  delay 0.2
  do script "cd '$ROOT_DIR'; bash -lc '$command'; exec bash" in front window
end tell
OSA
}

open_tab_fallback() {
  local title="$1"
  local cmd="$2"
  mkdir -p "$ROOT_DIR/logs"
  local log="$ROOT_DIR/logs/$(echo "$title" | tr ' /' '__').log"
  info "Starting $title (log: $log)"
  (cd "$ROOT_DIR" && bash -lc "$cmd") >>"$log" 2>&1 &
}

open_tab() {
  local title="$1"
  local cmd="$2"

  if [[ "$(uname -s)" == "Darwin" ]] && exists osascript; then
    open_tab_mac "$title" "$cmd" || open_tab_fallback "$title" "$cmd"
  else
    open_tab_fallback "$title" "$cmd"
  fi
}

# ==========================================================
# Argument parsing
# ==========================================================
MODE=""

for arg in "$@"; do
  case "$arg" in
    --mode=simulator) MODE="simulator" ;;
    --mode=odoo) MODE="odoo" ;;
    --help|-h)
      cat <<EOF
Usage:
  ./scripts/run-all.sh
  ./scripts/run-all.sh --mode=simulator
  ./scripts/run-all.sh --mode=odoo

Env:
  K8S_NAMESPACE=$K8S_NAMESPACE
  ODOO_LABEL_SELECTOR=$ODOO_LABEL_SELECTOR
EOF
      exit 0
      ;;
    *)
      err "Unknown argument: $arg"
      exit 1
      ;;
  esac
done

# ==========================================================
# Interactive selection (if MODE not provided)
# ==========================================================
if [[ -z "$MODE" ]]; then
  bold "SmartOps run-all: runtime selection"

  if detect_odoo_present; then
    info "Odoo detected in Kubernetes → default = Odoo"
    default_choice="2"
  else
    warn "Odoo not detected → default = ERP Simulator"
    default_choice="1"
  fi

  echo
  echo "Choose ERP source:"
  echo "  1) ERP Simulator (local)"
  echo "  2) Odoo (Kubernetes)"
  echo
  read -r -p "Enter choice [default ${default_choice}]: " choice
  choice="${choice:-$default_choice}"

  if [[ "$choice" == "2" ]]; then
    MODE="odoo"
  else
    MODE="simulator"
  fi
fi

# ==========================================================
# MODE → PROFILE sync (CRITICAL)
# ==========================================================
if [[ "$MODE" == "odoo" ]]; then
  export PROFILE="odoo"
elif [[ "$MODE" == "simulator" ]]; then
  export PROFILE="simulator"
else
  err "Invalid MODE: $MODE"
  exit 1
fi

# Validate PROFILE explicitly
case "$PROFILE" in
  simulator|odoo) ;;
  *)
    err "Invalid PROFILE='$PROFILE' (allowed: simulator | odoo)"
    exit 1
    ;;
esac

# ==========================================================
# Validate scripts
# ==========================================================
require_file "$CMD_AGENT_DETECT"
require_file "$CMD_AGENT_DIAGNOSE"
require_file "$CMD_POLICY_ENGINE"
require_file "$CMD_ORCHESTRATOR"
require_file "$CMD_DASHBOARD"

# ==========================================================
# Pre-flight checks
# ==========================================================
if [[ "$MODE" == "simulator" ]]; then
  require_file "$CMD_ERP_SIM"
  info "Mode selected: ERP Simulator"
else
  info "Mode selected: Odoo (Kubernetes)"
  detect_k8s_ready || { err "Kubernetes not reachable"; exit 1; }
  detect_odoo_present || {
    err "Odoo pods not detected in $K8S_NAMESPACE with selector '$ODOO_LABEL_SELECTOR'"
    exit 1
  }
fi

# ==========================================================
# Launch modules
# ==========================================================
bold "Launching SmartOps modules in separate tabs…"

if [[ "$MODE" == "simulator" ]]; then
  open_tab "ERP Simulator" "bash -lc '$CMD_ERP_SIM'"
else
  open_tab "Odoo Pods Watch" "bash -lc 'kubectl -n \"$K8S_NAMESPACE\" get pods -l \"$ODOO_LABEL_SELECTOR\" -w'"
fi

sleep 0.4; open_tab "Agent Detect"   "bash -lc '$CMD_AGENT_DETECT'"
sleep 0.4; open_tab "Agent Diagnose" "bash -lc '$CMD_AGENT_DIAGNOSE'"
sleep 0.4; open_tab "Policy Engine"  "bash -lc '$CMD_POLICY_ENGINE'"
sleep 0.4; open_tab "Orchestrator"   "bash -lc '$CMD_ORCHESTRATOR'"
sleep 0.4; open_tab "Dashboard"      "bash -lc '$CMD_DASHBOARD'"

echo
bold "Done."
info "All SmartOps modules launched with PROFILE=$PROFILE"
