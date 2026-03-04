# smartops_e2e.ps1
# SmartOps End-to-End Verifier (ERP Simulator / Odoo)
# Monitor → Detect → Diagnose → Decide → Act → Verify

$ErrorActionPreference = "Stop"

# -----------------------
# Constants
# -----------------------
$NS      = "smartops-dev"
$ORCH    = "http://smartops-orchestrator:8001"
$SIM_API = "http://smartops-erp-simulator:8000"

$DEP_SIM  = "smartops-erp-simulator"
$DEP_ODOO = "odoo-web"

$DET_SIM  = "smartops-agent-detect-sim"
$DET_ODOO = "smartops-agent-detect-odoo"
$DIAG_SIM = "smartops-agent-diagnose-sim"
$DIAG_ODOO= "smartops-agent-diagnose-odoo"

# log windows (increase if you want)
$ORCH_SINCE_DEFAULT = "90m"
$ORCH_TAIL_DEFAULT  = 60000

# how long we'll keep trying to get an "action-executed" window
$ACTION_QUALIFY_DEADLINE_SEC = 420  # 7 min total loop after trigger

# -----------------------
# Helpers
# -----------------------
function Write-Section($title) {
  Write-Host ""
  Write-Host "============================================================"
  Write-Host $title
  Write-Host "============================================================"
}

function Invoke-OrchRecent($limit = 80) {
  $cmd = @"
kubectl -n $NS run curlpod --image=curlimages/curl:8.5.0 --restart=Never -i --rm -- sh -lc "curl -sS '$ORCH/v1/signals/recent?limit=$limit' ; echo"
"@

  $rawLines = Invoke-Expression $cmd
  $rawText  = ($rawLines | Out-String)

  $start = $rawText.IndexOf('{')
  $end   = $rawText.LastIndexOf('}')
  if ($start -lt 0 -or $end -lt 0 -or $end -le $start) {
    throw "Invoke-OrchRecent: Could not locate JSON object in curlpod output. Raw was:`n$rawText"
  }

  $json = $rawText.Substring($start, $end - $start + 1)
  return ($json | ConvertFrom-Json)
}

function Get-DeployReplicas($dep) {
  $out = kubectl -n $NS get deploy $dep -o json | ConvertFrom-Json
  return [int]($out.spec.replicas)
}

function Get-DeployReady($dep) {
  $out = kubectl -n $NS get deploy $dep -o json | ConvertFrom-Json
  if ($null -eq $out.status.readyReplicas) { return 0 }
  return [int]($out.status.readyReplicas)
}

function Assert-Rollout($dep, $timeout = "300s") {
  kubectl -n $NS rollout status deploy/$dep --timeout=$timeout | Out-Host
}

function Wait-ForReplicasAtLeast($dep, $minReplicas, $timeoutSec = 240) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    $cur = Get-DeployReplicas $dep
    $ready = Get-DeployReady $dep
    if ($cur -ge $minReplicas -and $ready -ge $minReplicas) {
      Write-Host "OK: $dep replicas=$cur ready=$ready (>= $minReplicas)"
      return
    }
    Write-Host "Waiting: $dep replicas=$cur ready=$ready (need >= $minReplicas)..."
    Start-Sleep -Seconds 5
  }
  throw "Timeout: $dep did not reach replicas/ready >= $minReplicas within $timeoutSec seconds."
}

function Trigger-SimCpuLoad($seconds = 30) {
  Write-Section "Monitor trigger (ERP Simulator): simulate CPU load for ${seconds}s"
  $json = "{`"duration_seconds`":$seconds,`"target`":`"cpu`"}"
  $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
  kubectl -n $NS run curlpod --image=curlimages/curl:8.5.0 --restart=Never -i --rm -- sh -lc "echo '$b64' | base64 -d | curl -sS -X POST $SIM_API/simulate/load -H 'Content-Type: application/json' --data-binary @- ; echo" | Out-Host
}

function Trigger-OdooNoEndpoint() {
  Write-Section "Monitor trigger (Odoo): scale odoo-web to 0 (creates no-endpoint ingress signal)"
  kubectl -n $NS scale deploy/$DEP_ODOO --replicas=0 | Out-Host
  Assert-Rollout $DEP_ODOO "300s"
}

function Restore-Odoo() {
  Write-Section "Restore (Odoo): scale odoo-web back to 1"
  kubectl -n $NS scale deploy/$DEP_ODOO --replicas=1 | Out-Host
  Assert-Rollout $DEP_ODOO "300s"
  kubectl -n $NS get endpoints $DEP_ODOO | Out-Host
}

function Get-BaselineAnomalyIds($service) {
  $r = Invoke-OrchRecent 200
  $before = @()
  foreach ($a in $r.anomalies) {
    if ($a.service -eq $service) { $before += $a.windowId }
  }
  return $before
}

function Wait-NewAnomalyWindowId($service, $beforeIds, $timeoutSec = 240) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    $r = Invoke-OrchRecent 200
    foreach ($a in $r.anomalies) {
      if ($a.service -eq $service -and ($beforeIds -notcontains $a.windowId)) {
        return $a.windowId
      }
    }
    Start-Sleep -Seconds 3
  }
  throw "Timeout: did not observe a NEW anomaly for service '$service' within $timeoutSec seconds."
}

function Wait-RcaForWindow($service, $windowId, $timeoutSec = 240) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    $r = Invoke-OrchRecent 300
    foreach ($x in $r.rcas) {
      if ($x.service -eq $service -and $x.windowId -eq $windowId) { return $x }
    }
    Start-Sleep -Seconds 3
  }
  throw "Timeout: did not observe RCA for service '$service' windowId '$windowId' within $timeoutSec seconds."
}

function Get-OrchLogLines($since = $ORCH_SINCE_DEFAULT, $tail = $ORCH_TAIL_DEFAULT) {
  return (kubectl -n $NS logs deploy/smartops-orchestrator --since=$since --tail=$tail)
}

function Get-TraceIdForWindow($windowId, $since = $ORCH_SINCE_DEFAULT) {
  $lines = Get-OrchLogLines $since $ORCH_TAIL_DEFAULT
  $hit = $lines | Where-Object { $_ -match [regex]::Escape($windowId) } | Select-Object -First 1
  if (-not $hit) { return $null }

  $m = [regex]::Match($hit, "trace_id=([0-9a-f]+)")
  if ($m.Success) { return $m.Groups[1].Value }
  return $null
}

function Get-OrchEvidenceByTrace($traceId, $since = $ORCH_SINCE_DEFAULT) {
  $lines = Get-OrchLogLines $since $ORCH_TAIL_DEFAULT

  $interesting = $lines |
    Where-Object { $_ -match ("trace_id=" + [regex]::Escape($traceId)) } |
    Where-Object {
      $_ -match "SIGNAL_RAW" -or
      $_ -match "POLICY_ENGINE payload" -or
      $_ -match "POLICY_ENGINE_RESPONSE" -or
      $_ -match "ClosedLoopManager:" -or
      $_ -match "Executing action:" -or
      $_ -match "Action completed:" -or
      $_ -match "verified successfully" -or
      $_ -match "CLOSED_LOOP_SUMMARY" -or
      $_ -match "guardrail" -or
      $_ -match "cooldown" -or
      $_ -match "policy denied"
    }

  return $interesting
}

function Classify-TraceEvidence($ev) {
  # returns hasExecute/hasDone/hasVerify/hasSummary + skip reasons
  $hasExecute = $ev | Where-Object { $_ -match "ClosedLoopManager: executing" } | Select-Object -First 1
  $hasDone    = $ev | Where-Object { $_ -match "Action completed:" } | Select-Object -First 1
  $hasVerify  = $ev | Where-Object { $_ -match "verified successfully" } | Select-Object -First 1
  $hasSummary = $ev | Where-Object { $_ -match "CLOSED_LOOP_SUMMARY" } | Select-Object -First 1

  $cooldown   = $ev | Where-Object { $_ -match "cooldown active" } | Select-Object -First 1
  $guardrail  = $ev | Where-Object { $_ -match "guardrail" } | Select-Object -First 1
  $denied     = $ev | Where-Object { $_ -match "policy denied execution" -or $_ -match '"decision"\s*:\s*"no_action"' } | Select-Object -First 1

  return @{
    hasExecute = [bool]$hasExecute
    hasDone    = [bool]$hasDone
    hasVerify  = [bool]$hasVerify
    hasSummary = [bool]$hasSummary
    cooldown   = [bool]$cooldown
    guardrail  = [bool]$guardrail
    denied     = [bool]$denied
  }
}

function Wait-OrchestratorActionForWindow($windowId, $timeoutSec = 240, $since = $ORCH_SINCE_DEFAULT) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    $traceId = Get-TraceIdForWindow $windowId $since
    if ($traceId) {
      $ev = Get-OrchEvidenceByTrace $traceId $since
      $c = Classify-TraceEvidence $ev

      if ($c.hasExecute -or $c.hasDone -or $c.hasVerify -or $c.hasSummary) {
        return @{ traceId = $traceId; evidence = $ev; classify = $c }
      }
      # If we see explicit skip reasons, return them too (caller may choose to skip this window)
      if ($c.cooldown -or $c.guardrail -or $c.denied) {
        return @{ traceId = $traceId; evidence = $ev; classify = $c }
      }
    }
    Start-Sleep -Seconds 5
  }
  return $null
}

function Wait-ForActionQualifiedWindow($service, $beforeIds, $overallTimeoutSec, $since = $ORCH_SINCE_DEFAULT) {
  $deadline = (Get-Date).AddSeconds($overallTimeoutSec)
  $seen = @{}  # windowId -> true

  while ((Get-Date) -lt $deadline) {
    $wid = Wait-NewAnomalyWindowId $service $beforeIds 120
    if ($seen.ContainsKey($wid)) { continue }
    $seen[$wid] = $true
    $beforeIds += $wid

    Write-Host "Candidate windowId=$wid (waiting for orchestrator trace/evidence...)"

    $info = Wait-OrchestratorActionForWindow $wid 180 $since
    if (-not $info) {
      Write-Host "Candidate windowId=${wid}: no trace/evidence yet; skipping and waiting next..."
      continue
    }

    $c = $info.classify

    if ($c.hasExecute -or $c.hasDone -or $c.hasVerify -or $c.hasSummary) {
      Write-Host "Candidate windowId=$wid is ACTION-QUALIFIED (trace_id=$($info.traceId))"
      return @{ windowId = $wid; traceId = $info.traceId; evidence = $info.evidence; classify = $c }
    }

    if ($c.cooldown) {
      Write-Host "Candidate windowId=$wid skipped due to COOLDOWN (will wait next anomaly)..."
      continue
    }
    if ($c.guardrail) {
      Write-Host "Candidate windowId=$wid skipped due to GUARDRAIL (will wait next anomaly)..."
      continue
    }
    if ($c.denied) {
      Write-Host "Candidate windowId=$wid policy DENIED (will wait next anomaly)..."
      continue
    }

    Write-Host "Candidate windowId=$wid did not qualify; waiting next..."
  }

  return $null
}

function Show-OrchestratorEvidence($windowId) {
  Write-Section "Decide / Act / Verify evidence (orchestrator logs) for windowId=$windowId (trace-correlated)"
  $traceId = Get-TraceIdForWindow $windowId $ORCH_SINCE_DEFAULT
  if (-not $traceId) {
    Write-Host "Could not find trace_id for windowId=$windowId in orchestrator logs (since=$ORCH_SINCE_DEFAULT)."
    return
  }
  Write-Host "trace_id=$traceId"
  $ev = Get-OrchEvidenceByTrace $traceId $ORCH_SINCE_DEFAULT
  $ev | Select-Object -Last 220 | ForEach-Object { $_ }
}

function Ensure-DeployReplicasExact($dep, $desired, $timeout = "300s") {
  $cur = Get-DeployReplicas $dep
  if ($cur -ne $desired) {
    Write-Host "Setting $dep replicas=$desired (was $cur) ..."
    kubectl -n $NS scale deploy/$dep --replicas=$desired | Out-Host
    Assert-Rollout $dep $timeout
  } else {
    Write-Host "$dep replicas already $desired"
  }
}

# -----------------------
# Menu
# -----------------------
Write-Section "SmartOps E2E Verifier"
Write-Host "Choose target:"
Write-Host "  1) ERP Simulator  (service=erp-simulator)"
Write-Host "  2) Odoo           (service=odoo)"
$choice = Read-Host "Enter 1 or 2"

if ($choice -ne "1" -and $choice -ne "2") { throw "Invalid choice. Run again and enter 1 or 2." }

# -----------------------
# ERP Simulator flow
# -----------------------
if ($choice -eq "1") {
  $service = "erp-simulator"

  Write-Section "Pre-check: ensure split deployments are running (detect + diagnose)"
  kubectl -n $NS get deploy $DET_SIM $DIAG_SIM | Out-Host

  $detReady = Get-DeployReady $DET_SIM
  if ($detReady -lt 1) {
    throw "$DET_SIM is not ready (ready=$detReady). Fix agent-detect-sim before running E2E."
  }

  Write-Section "Pre-check: force simulator to replicas=3 so policy step_1 matches (replicas.current=3)"
  Ensure-DeployReplicasExact $DEP_SIM 3 "300s"

  Write-Section "MONITOR: capture baseline signals"
  $beforeIds = Get-BaselineAnomalyIds $service
  Write-Host "Baseline anomaly windowIds(count=$($beforeIds.Count)) captured."

  Trigger-SimCpuLoad 30

  Write-Section "DETECT→DECIDE/ACT: waiting for an ACTION-QUALIFIED anomaly windowId (auto-skip cooldown/guardrail/denied)"
  $picked = Wait-ForActionQualifiedWindow $service $beforeIds $ACTION_QUALIFY_DEADLINE_SEC $ORCH_SINCE_DEFAULT
  if (-not $picked) {
    throw "Timeout: did not observe an action-qualified anomaly for '$service' within $ACTION_QUALIFY_DEADLINE_SEC seconds."
  }

  $wid = $picked.windowId
  Write-Host "Using windowId=$wid (trace_id=$($picked.traceId))"

  Write-Section "DIAGNOSE: waiting for RCA for same windowId"
  $rca = Wait-RcaForWindow $service $wid 240
  Write-Host "RCA received for windowId=$($rca.windowId) confidence=$($rca.confidence)"
  Write-Host ("Top cause: " + $rca.rankedCauses[0].cause + " prob=" + $rca.rankedCauses[0].probability)

  Show-OrchestratorEvidence $wid

  Write-Section "VERIFY (K8s): wait for post-action scale to take effect (>=4 ready)"
  Wait-ForReplicasAtLeast $DEP_SIM 4 420
  kubectl -n $NS get deploy $DEP_SIM -o wide | Out-Host

  $finalReplicas = Get-DeployReplicas $DEP_SIM
  $finalReady    = Get-DeployReady $DEP_SIM
  if ($finalReplicas -ge 6) {
    Write-Host "NOTE: deployment reached replicas=$finalReplicas (likely policy step_2 triggered quickly)."
  } elseif ($finalReplicas -eq 4) {
    Write-Host "NOTE: deployment stabilized at replicas=4 (policy step_1 target)."
  } else {
    Write-Host "NOTE: deployment replicas ended at $finalReplicas (unexpected but accepted since ready>=4)."
  }

  Write-Section "FINAL (signals/recent): confirm anomaly + rca share same windowId"
  $r = Invoke-OrchRecent 300
  $hasA = $false
  $hasR = $false
  foreach ($a in $r.anomalies) { if ($a.service -eq $service -and $a.windowId -eq $wid) { $hasA = $true } }
  foreach ($x in $r.rcas)      { if ($x.service -eq $service -and $x.windowId -eq $wid) { $hasR = $true } }
  Write-Host "anomaly_present=$hasA rca_present=$hasR windowId=$wid"
  if (-not ($hasA -and $hasR)) { throw "Signals check failed: missing anomaly or rca for windowId=$wid" }

  Write-Section "E2E SUCCESS: ERP Simulator"
  Write-Host "Monitor: simulate/load"
  Write-Host "Detect: anomaly windowId=$wid"
  Write-Host "Diagnose: RCA posted (same windowId)"
  Write-Host "Decide/Act/Verify: trace-correlated orchestrator evidence above"
}

# -----------------------
# Odoo flow
# -----------------------
if ($choice -eq "2") {
  $service = "odoo"

  Write-Section "Pre-check: ensure split deployments are running (detect + diagnose)"
  kubectl -n $NS get deploy $DET_ODOO $DIAG_ODOO | Out-Host

  $detReady = Get-DeployReady $DET_ODOO
  if ($detReady -lt 1) {
    throw "$DET_ODOO is not ready (ready=$detReady). Fix agent-detect-odoo before running E2E."
  }

  Write-Section "MONITOR: capture baseline signals"
  $beforeIds = Get-BaselineAnomalyIds $service
  Write-Host "Baseline anomaly windowIds(count=$($beforeIds.Count)) captured."

  Trigger-OdooNoEndpoint

  Write-Section "DETECT→DECIDE/ACT: waiting for an ACTION-QUALIFIED anomaly windowId (auto-skip cooldown/guardrail/denied)"
  $picked = Wait-ForActionQualifiedWindow $service $beforeIds 360 $ORCH_SINCE_DEFAULT
  if (-not $picked) {
    Show-OrchestratorEvidence $wid
    throw "Timeout: did not observe an action-qualified anomaly for '$service' within 360 seconds."
  }

  $wid = $picked.windowId
  Write-Host "Using windowId=$wid (trace_id=$($picked.traceId))"

  Write-Section "DIAGNOSE: waiting for RCA for same windowId"
  $rca = Wait-RcaForWindow $service $wid 240
  Write-Host "RCA received for windowId=$($rca.windowId) confidence=$($rca.confidence)"
  Write-Host ("Top cause: " + $rca.rankedCauses[0].cause + " prob=" + $rca.rankedCauses[0].probability)

  Show-OrchestratorEvidence $wid

  Write-Section "VERIFY (K8s): odoo deployment + endpoints (should be 0 at this point)"
  kubectl -n $NS get deploy $DEP_ODOO -o wide | Out-Host
  kubectl -n $NS get endpoints $DEP_ODOO | Out-Host

  Restore-Odoo

  Write-Section "FINAL (signals/recent): confirm anomaly + rca share same windowId"
  $r = Invoke-OrchRecent 300
  $hasA = $false
  $hasR = $false
  foreach ($a in $r.anomalies) { if ($a.service -eq $service -and $a.windowId -eq $wid) { $hasA = $true } }
  foreach ($x in $r.rcas)      { if ($x.service -eq $service -and $x.windowId -eq $wid) { $hasR = $true } }
  Write-Host "anomaly_present=$hasA rca_present=$hasR windowId=$wid"
  if (-not ($hasA -and $hasR)) { throw "Signals check failed: missing anomaly or rca for windowId=$wid" }

  Write-Section "E2E SUCCESS: Odoo"
  Write-Host "Monitor: scale odoo-web to 0 (no-endpoint) then restore"
  Write-Host "Detect: anomaly windowId=$wid"
  Write-Host "Diagnose: RCA posted (same windowId)"
  Write-Host "Decide/Act/Verify: trace-correlated orchestrator evidence above"
}