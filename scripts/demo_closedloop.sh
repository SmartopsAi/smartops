#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="smartops-dev"
SERVICE="smartops-orchestrator"
PORT="8001"

WINDOW_ID="demo-$(date +%s)"

echo "=========================================="
echo " SmartOps Closed-Loop Demo (Production)"
echo "=========================================="
echo "Namespace : $NAMESPACE"
echo "Window ID : $WINDOW_ID"
echo ""

echo "[1/5] Capturing current ERP pod..."
OLD_POD=$(kubectl -n $NAMESPACE get pods -l app=smartops-erp-simulator -o jsonpath='{.items[0].metadata.name}')
echo "Current ERP pod: $OLD_POD"
echo ""

echo "[2/5] Sending anomaly signal (in-cluster)..."
kubectl -n $NAMESPACE run tmp-curl --rm -i --restart=Never \
  --image=curlimages/curl:8.5.0 \
  -- curl -s -X POST http://$SERVICE:$PORT/v1/signals/anomaly \
  -H "Content-Type: application/json" \
  -d "{
        \"service\": \"erp-simulator\",
        \"windowId\": \"$WINDOW_ID\",
        \"type\": \"resource\",
        \"score\": 1.0,
        \"isAnomaly\": true
      }"

echo ""
echo "[3/5] Waiting for closed-loop execution..."
sleep 8

echo ""
echo "[4/5] Checking CLOSED_LOOP_SUMMARY log..."
kubectl -n $NAMESPACE logs deploy/smartops-orchestrator \
  | grep "$WINDOW_ID" -B 2 -A 2 || true

echo ""
echo "[5/5] Checking ERP pod restart..."
NEW_POD=$(kubectl -n $NAMESPACE get pods -l app=smartops-erp-simulator -o jsonpath='{.items[0].metadata.name}')
echo "New ERP pod: $NEW_POD"

if [[ "$OLD_POD" != "$NEW_POD" ]]; then
  echo ""
  echo "✅ Pod restart detected."
else
  echo ""
  echo "⚠️  Pod name unchanged (may have restarted in-place)."
fi

echo ""
echo "=========================================="
echo " Demo Complete"
echo "=========================================="

