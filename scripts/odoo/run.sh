#!/usr/bin/env bash
set -euo pipefail

echo ""
echo "🚀 SmartOps Odoo (K8s-first, production-grade)"
echo ""

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT"

NAMESPACE="${SMARTOPS_NAMESPACE:-smartops-dev}"
RELEASE="${ODOO_HELM_RELEASE:-smartops-odoo}"
INGRESS_NAME="${ODOO_INGRESS_NAME:-odoo-ingress}"
SERVICE_WEB="${ODOO_WEB_SERVICE:-odoo-web}"
SERVICE_DB="${ODOO_DB_SERVICE:-odoo-postgres}"
DEPLOY_WEB="${ODOO_WEB_DEPLOY:-odoo-web}"
STS_DB="${ODOO_DB_STS:-odoo-postgres}"
LOCAL_PORT="${ODOO_LOCAL_PORT:-8069}"
INGRESS_HOST="${ODOO_INGRESS_HOST:-odoo.localhost}"

need() { command -v "$1" >/dev/null 2>&1 || { echo "❌ Missing: $1"; exit 1; }; }
need kubectl
need helm

echo "📁 Project root: $PROJECT_ROOT"
echo "🧭 Namespace:    $NAMESPACE"
echo "📦 Helm release: $RELEASE"
echo ""

# ---- sanity: cluster reachable
if ! kubectl version --client >/dev/null 2>&1; then
  echo "❌ kubectl not configured."
  exit 1
fi

# ---- ensure release exists (install only if you want; default: do not auto-install)
if ! helm status "$RELEASE" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "❌ Helm release '$RELEASE' not found in namespace '$NAMESPACE'."
  echo "👉 Install via your umbrella chart / helm install step (recommended)."
  exit 1
fi

echo "⏳ Waiting for Odoo + Postgres to be Ready..."
kubectl rollout status deploy/"$DEPLOY_WEB" -n "$NAMESPACE" --timeout=180s
kubectl rollout status statefulset/"$STS_DB" -n "$NAMESPACE" --timeout=180s
echo "✅ Workloads are Ready."
echo ""

# ---- Try ingress first
if kubectl get ingress "$INGRESS_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "🌐 Ingress detected: $INGRESS_NAME"
  echo "🔗 Try: http://$INGRESS_HOST"
  echo ""
  echo "🔎 Quick check (expect HTTP 200/303):"
  curl -I "http://$INGRESS_HOST" || true
  echo ""
  echo "✅ Done (Ingress path)."
  exit 0
fi

# ---- Fallback: port-forward service
echo "⚠️ Ingress not found. Falling back to port-forward."
echo "➡️ Port-forwarding service/$SERVICE_WEB $LOCAL_PORT:8069 (CTRL+C to stop)"
echo "🔗 http://127.0.0.1:$LOCAL_PORT"
echo ""

kubectl -n "$NAMESPACE" port-forward svc/"$SERVICE_WEB" "$LOCAL_PORT":8069
