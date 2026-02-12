#!/usr/bin/env bash
set -euo pipefail
NAMESPACE="${SMARTOPS_NAMESPACE:-smartops-dev}"

echo "== Odoo Status ($NAMESPACE) =="
kubectl get pods,svc,ingress -n "$NAMESPACE" | grep -iE "odoo|NAME|postgres" || true
echo ""
kubectl get deploy -n "$NAMESPACE" odoo-web -o wide || true
kubectl get statefulset -n "$NAMESPACE" odoo-postgres -o wide || true
