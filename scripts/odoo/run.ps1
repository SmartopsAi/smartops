 $ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "🚀 SmartOps Odoo (K8s-first, production-grade)"
Write-Host ""

$PROJECT_ROOT = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $PROJECT_ROOT

$NAMESPACE   = if ($env:SMARTOPS_NAMESPACE) { $env:SMARTOPS_NAMESPACE } else { "smartops-dev" }
$RELEASE     = if ($env:ODOO_HELM_RELEASE) { $env:ODOO_HELM_RELEASE } else { "smartops-odoo" }
$INGRESSNAME = if ($env:ODOO_INGRESS_NAME) { $env:ODOO_INGRESS_NAME } else { "odoo-ingress" }
$SERVICE_WEB = if ($env:ODOO_WEB_SERVICE) { $env:ODOO_WEB_SERVICE } else { "odoo-web" }
$DEPLOY_WEB  = if ($env:ODOO_WEB_DEPLOY) { $env:ODOO_WEB_DEPLOY } else { "odoo-web" }
$STS_DB      = if ($env:ODOO_DB_STS) { $env:ODOO_DB_STS } else { "odoo-postgres" }
$LOCAL_PORT  = if ($env:ODOO_LOCAL_PORT) { $env:ODOO_LOCAL_PORT } else { "8069" }
$INGRESSHOST = if ($env:ODOO_INGRESS_HOST) { $env:ODOO_INGRESS_HOST } else { "odoo.localhost" }

Write-Host "📁 Project root: $PROJECT_ROOT"
Write-Host "🧭 Namespace:    $NAMESPACE"
Write-Host "📦 Helm release: $RELEASE"
Write-Host ""

# Tools
if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) { throw "kubectl not found" }
if (-not (Get-Command helm -ErrorAction SilentlyContinue))   { throw "helm not found" }

# Ensure release exists
helm status $RELEASE -n $NAMESPACE | Out-Null

Write-Host "⏳ Waiting for Odoo + Postgres to be Ready..."
kubectl rollout status deploy/$DEPLOY_WEB -n $NAMESPACE --timeout=180s | Out-Host
kubectl rollout status statefulset/$STS_DB -n $NAMESPACE --timeout=180s | Out-Host
Write-Host "✅ Workloads are Ready."
Write-Host ""

# Ingress first
$ing = kubectl get ingress $INGRESSNAME -n $NAMESPACE 2>$null
if ($LASTEXITCODE -eq 0) {
  Write-Host "🌐 Ingress detected: $INGRESSNAME"
  Write-Host "🔗 Try: http://$INGRESSHOST"
  Write-Host ""
  try { curl.exe -I "http://$INGRESSHOST" | Out-Host } catch {}
  Write-Host "✅ Done (Ingress path)."
  exit 0
}

Write-Host "⚠️ Ingress not found. Falling back to port-forward."
Write-Host "➡️ Port-forwarding service/$SERVICE_WEB $LOCAL_PORT:8069 (CTRL+C to stop)"
Write-Host "🔗 http://127.0.0.1:$LOCAL_PORT"
Write-Host ""

kubectl -n $NAMESPACE port-forward svc/$SERVICE_WEB "$LOCAL_PORT`:8069"
