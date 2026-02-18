Param(
  [ValidateSet("simulator","odoo")]
  [string]$Mode = ""
)

$ErrorActionPreference = "Stop"

# ========= CONFIG (adjust if your paths differ) =========
$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")

$CmdErpSim       = ".\scripts\erp-sim\run.ps1"
$CmdAgentDetect  = ".\scripts\agent-detect\run.ps1"
$CmdAgentDiagnose= ".\scripts\agent-diagnose\run.ps1"
$CmdPolicyEngine = ".\scripts\policy-engine\run.ps1"
$CmdOrchestrator = ".\scripts\orchestrator\run.ps1"
$CmdDashboard    = ".\scripts\dashboard\run.ps1"

$K8sNamespace = $env:K8S_NAMESPACE
if ([string]::IsNullOrWhiteSpace($K8sNamespace)) { $K8sNamespace = "smartops-dev" }

$OdooLabelSelector = $env:ODOO_LABEL_SELECTOR
if ([string]::IsNullOrWhiteSpace($OdooLabelSelector)) { $OdooLabelSelector = "app.kubernetes.io/name=odoo" }

function Require-File($rel) {
  $p = Join-Path $RootDir $rel
  if (-not (Test-Path $p)) {
    throw "Missing: $p`nFix the path in scripts/run-all.ps1 CONFIG section."
  }
}

function Has-Command($name) {
  return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Detect-K8sReady {
  if (-not (Has-Command "kubectl")) { return $false }
  try {
    kubectl version --client | Out-Null
    kubectl cluster-info | Out-Null
    return $true
  } catch { return $false }
}

function Detect-OdooPresent {
  if (-not (Detect-K8sReady)) { return $false }
  try {
    kubectl get ns $K8sNamespace | Out-Null
    $pods = kubectl -n $K8sNamespace get pods -l $OdooLabelSelector --no-headers 2>$null
    return ($pods.Count -gt 0)
  } catch { return $false }
}

function Open-Tab($title, $command) {
  # Uses Windows Terminal tabs if available; otherwise opens new PowerShell windows.
  $wt = Get-Command "wt.exe" -ErrorAction SilentlyContinue
  if ($wt) {
    # New tab runs: pwsh -NoExit -Command "cd ...; <command>"
    & wt.exe new-tab --title "$title" pwsh -NoExit -Command "Set-Location -LiteralPath '$RootDir'; Write-Host ''; Write-Host '==== $title ===='; $command"
  } else {
    Start-Process pwsh -ArgumentList @("-NoExit","-Command", "Set-Location -LiteralPath '$RootDir'; Write-Host ''; Write-Host '==== $title ===='; $command")
  }
}

# ========= Validate required scripts =========
Require-File $CmdAgentDetect
Require-File $CmdAgentDiagnose
Require-File $CmdPolicyEngine
Require-File $CmdOrchestrator
Require-File $CmdDashboard

if ([string]::IsNullOrWhiteSpace($Mode)) {
  $default = if (Detect-OdooPresent) { "2" } else { "1" }

  Write-Host "SmartOps run-all: runtime selection"
  if ($default -eq "2") {
    Write-Host "Kubernetes reachable AND Odoo detected in namespace '$K8sNamespace'. Default = Odoo"
  } else {
    Write-Host "Odoo not detected (or cluster unreachable). Default = ERP Simulator"
  }

  Write-Host ""
  Write-Host "Choose ERP source:"
  Write-Host "  1) ERP Simulator (local)"
  Write-Host "  2) Odoo (Kubernetes)"
  Write-Host ""
  $choice = Read-Host "Enter choice [default $default]"
  if ([string]::IsNullOrWhiteSpace($choice)) { $choice = $default }

  $Mode = if ($choice -eq "2") { "odoo" } else { "simulator" }
}

if ($Mode -eq "simulator") {
  Require-File $CmdErpSim
  Write-Host "Mode: ERP Simulator"
} elseif ($Mode -eq "odoo") {
  Write-Host "Mode: Odoo (Kubernetes)"
  if (-not (Detect-K8sReady)) {
    throw "kubectl/Kubernetes not reachable. Fix kubeconfig/context and try again."
  }
  if (-not (Detect-OdooPresent)) {
    throw "Kubernetes reachable, but Odoo pods not detected in namespace '$K8sNamespace' with selector '$OdooLabelSelector'. Deploy Odoo or adjust env vars."
  }
} else {
  throw "Invalid mode: $Mode"
}

Write-Host "Launching SmartOps modules in separate tabs…"

if ($Mode -eq "simulator") {
  Open-Tab "ERP Simulator" "& $CmdErpSim"
} else {
  Open-Tab "Odoo (K8s) Watch" "kubectl -n $K8sNamespace get pods -l $OdooLabelSelector -w"
}

Start-Sleep -Milliseconds 400; Open-Tab "Agent Detect"   "& $CmdAgentDetect"
Start-Sleep -Milliseconds 400; Open-Tab "Agent Diagnose" "& $CmdAgentDiagnose"
Start-Sleep -Milliseconds 400; Open-Tab "Policy Engine"  "& $CmdPolicyEngine"
Start-Sleep -Milliseconds 400; Open-Tab "Orchestrator"   "& $CmdOrchestrator"
Start-Sleep -Milliseconds 400; Open-Tab "Dashboard"      "& $CmdDashboard"

Write-Host ""
Write-Host "Done."
