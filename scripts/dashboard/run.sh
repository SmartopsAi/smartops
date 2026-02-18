#!/usr/bin/env bash
set -e

echo ""
echo "🚀 Starting SmartOps Dashboard (Docker, production-grade)"
echo ""

# --------------------------------------------------
# Resolve project root
# --------------------------------------------------
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT"

echo "📁 Project root: $PROJECT_ROOT"

# --------------------------------------------------
# Docker check
# --------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  echo "❌ Docker not found. Please install Docker Desktop."
  exit 1
fi

# --------------------------------------------------
# Config
# --------------------------------------------------
IMAGE_NAME="smartops-dashboard:local"
CONTAINER_NAME="smartops-dashboard-local"

DASHBOARD_PORT=8080
POLICY_ENGINE_URL="${POLICY_ENGINE_URL:-http://localhost:8002}"

echo "🌐 Dashboard URL: http://localhost:${DASHBOARD_PORT}"
echo "🔗 Policy Engine: ${POLICY_ENGINE_URL}"

# --------------------------------------------------
# Build image
# --------------------------------------------------
echo "📦 Building Dashboard Docker image..."
docker build \
  -t "${IMAGE_NAME}" \
  -f apps/dashboard/Dockerfile \
  .

# --------------------------------------------------
# Cleanup old container
# --------------------------------------------------
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "🧹 Removing existing container..."
  docker rm -f "${CONTAINER_NAME}"
fi

# --------------------------------------------------
# Run container
# --------------------------------------------------
echo ""
echo "▶️  Starting Dashboard container..."
echo "🛑 Stop with CTRL+C"
echo ""

docker run \
  --name "${CONTAINER_NAME}" \
  -p ${DASHBOARD_PORT}:80 \
  -e DASHBOARD_PORT=80 \
  -e POLICY_ENGINE_URL="${POLICY_ENGINE_URL}" \
  -e SMARTOPS_ENV=local \
  -v "${PROJECT_ROOT}/data/runtime:/app/data/runtime:ro" \
  "${IMAGE_NAME}"
