#!/usr/bin/env bash
set -e

echo ""
echo "📈 SmartOps Prometheus – Local Access"
echo ""

# -------------------------------
# Auto-detect namespace
# -------------------------------
NAMESPACE=$(kubectl get ns -o jsonpath='{.items[*].metadata.name}' | tr ' ' '\n' | grep smartops | head -n1)

if [ -z "$NAMESPACE" ]; then
  echo "❌ SmartOps namespace not found"
  exit 1
fi

echo "📦 Namespace detected: $NAMESPACE"

# -------------------------------
# Detect Prometheus pod
# -------------------------------
PROM_POD=$(kubectl get pods -n "$NAMESPACE" \
  | grep prometheus \
  | grep Running \
  | awk '{print $1}' \
  | head -n1)

if [ -z "$PROM_POD" ]; then
  echo "❌ Prometheus pod not found"
  exit 1
fi

# -------------------------------
# Port forward
# -------------------------------
LOCAL_PORT=9090
LOG_FILE="logs/prometheus.log"
PID_FILE="pids/prometheus.pid"

echo "🔌 Port-forwarding Prometheus → http://localhost:$LOCAL_PORT"

kubectl port-forward -n "$NAMESPACE" "$PROM_POD" $LOCAL_PORT:9090 \
  > "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"

echo "✅ Prometheus running"
echo "📄 Logs: $LOG_FILE"
echo "🆔 PID : $(cat $PID_FILE)"
echo ""
