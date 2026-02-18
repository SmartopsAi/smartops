Write-Host ""
Write-Host "🚀 Starting SmartOps Dashboard (Docker, production-grade)"
Write-Host ""

$PROJECT_ROOT = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $PROJECT_ROOT

$IMAGE_NAME = "smartops-dashboard:local"
$CONTAINER_NAME = "smartops-dashboard-local"

$DASHBOARD_PORT = 8080
$POLICY_ENGINE_URL = $env:POLICY_ENGINE_URL
if (-not $POLICY_ENGINE_URL) {
    $POLICY_ENGINE_URL = "http://localhost:8002"
}

Write-Host "📁 Project root:" $PROJECT_ROOT
Write-Host "🌐 Dashboard URL: http://localhost:$DASHBOARD_PORT"
Write-Host "🔗 Policy Engine:" $POLICY_ENGINE_URL

# Docker check
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Docker not found. Install Docker Desktop."
    exit 1
}

Write-Host "📦 Building Dashboard Docker image..."
docker build `
  -t $IMAGE_NAME `
  -f apps/dashboard/Dockerfile `
  .

if (docker ps -a --format "{{.Names}}" | Select-String "^$CONTAINER_NAME$") {
    Write-Host "🧹 Removing existing container..."
    docker rm -f $CONTAINER_NAME
}

Write-Host ""
Write-Host "▶️  Starting Dashboard container..."
Write-Host "🛑 Stop with CTRL+C"
Write-Host ""

docker run `
  --name $CONTAINER_NAME `
  -p ${DASHBOARD_PORT}:80 `
  -e DASHBOARD_PORT=80 `
  -e POLICY_ENGINE_URL=$POLICY_ENGINE_URL `
  -e SMARTOPS_ENV=local `
  -v "${PROJECT_ROOT}\data\runtime:/app/data/runtime:ro" `
  $IMAGE_NAME
