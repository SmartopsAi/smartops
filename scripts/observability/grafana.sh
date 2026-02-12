#!/usr/bin/env bash
set -e

echo ""
echo "📊 SmartOps Grafana – Local Access"
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
# Detect Grafana service
# -------------------------------
GRAFANA_SVC=$(kubectl get svc -n "$NAMESPACE" \
  | grep grafana \
  | awk '{print $1}' \
  | head -n1)

if [ -z "$GRAFANA_SVC" ]; then
  echo "❌ Grafana service not found"
  exit 1
fi

# -------------------------------
# Port forward
# -------------------------------
LOCAL_PORT=3000
LOG_FILE="logs/grafana.log"
PID_FILE="pids/grafana.pid"

echo "🔌 Port-forwarding Grafana → http://localhost:$LOCAL_PORT"

kubectl port-forward -n "$NAMESPACE" svc/"$GRAFANA_SVC" $LOCAL_PORT:80 \
  > "$LOG_FILE" 2>&1 &

echo $! > "$PID_FILE"

# -------------------------------
# Credentials (best-effort)
# -------------------------------
echo ""
echo "🔐 Default Grafana credentials (if unchanged):"
echo "   user: admin"
echo "   pass: admin"
echo ""

echo "✅ Grafana running"
echo "📄 Logs: $LOG_FILE"
echo "🆔 PID : $(cat $PID_FILE)"
echo ""
