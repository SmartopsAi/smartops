$ns = "smartops-dev"

function Wait-ForRestartSuccess {
    param(
        [int]$TimeoutSeconds = 180
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        $logs = kubectl logs -n $ns deploy/smartops-orchestrator --tail=1200 2>&1
        if ($logs | Select-String "CLOSED_LOOP_SUMMARY .*action=restart.*result=SUCCESS") {
            return $true
        }
        Start-Sleep -Seconds 3
    }

    return $false
}

function Wait-ForBlockedCooldown {
    param(
        [int]$TimeoutSeconds = 180
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $deadline) {
        $policyJson = kubectl run -n $ns curlpod --image=curlimages/curl:8.5.0 --restart=Never -i --rm -- `
            curl -sS "http://smartops-policy-engine:5051/v1/policy/audit/latest?n=30" 2>$null

        if ($policyJson) {
            try {
                $policy = $policyJson | ConvertFrom-Json
                foreach ($event in ($policy.events | Select-Object -First 30)) {
                    if (
                        $event.policy -eq "restart_on_anomaly_error" -and
                        $event.decision -eq "blocked" -and
                        "$($event.guardrail_reason)" -match "restart cooldown"
                    ) {
                        return $event
                    }
                }
            } catch {
            }
        }

        $logs = kubectl logs -n $ns deploy/smartops-orchestrator --tail=1200 2>&1
        if ($logs | Select-String "policy denied execution" | Select-String "restart cooldown") {
            # keep waiting for policy event JSON so backend can bind properly
        }

        Start-Sleep -Seconds 3
    }

    return $null
}

Write-Host "== Reset to normal =="
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pp2\reset-to-normal.ps1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Reset failed."
    exit 1
}

Write-Host "`n== Set demo cooldown to 120 seconds on orchestrator =="
kubectl set env deploy/smartops-orchestrator -n $ns COOLDOWN_ENABLED=1 CLOSED_LOOP_COOLDOWN_SECONDS=120
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to set cooldown env vars."
    exit 1
}
kubectl rollout restart deploy/smartops-orchestrator -n $ns
if ($LASTEXITCODE -ne 0) {
    Write-Error "Failed to restart orchestrator."
    exit 1
}
kubectl rollout status deploy/smartops-orchestrator -n $ns --timeout=180s
if ($LASTEXITCODE -ne 0) {
    Write-Error "Orchestrator rollout did not complete."
    exit 1
}

Write-Host "`n== First error run: should restart successfully =="
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pp2\run-restart-error.ps1
if ($LASTEXITCODE -ne 0) {
    Write-Error "First restart-error run failed."
    exit 1
}

Write-Host "`n== Wait for first restart success =="
$restartSucceeded = Wait-ForRestartSuccess -TimeoutSeconds 180
if (-not $restartSucceeded) {
    Write-Error "Did not observe first restart success."
    exit 1
}

Write-Host "`n== Second error run: should be blocked by cooldown =="
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\pp2\run-restart-error.ps1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Second restart-error run failed."
    exit 1
}

Write-Host "`n== Wait for blocked restart cooldown policy event =="
$blockedEvent = Wait-ForBlockedCooldown -TimeoutSeconds 180
if (-not $blockedEvent) {
    Write-Error "Did not observe blocked restart cooldown event."
    exit 1
}

Write-Host "`n== Blocked event found =="
$blockedEvent | ConvertTo-Json -Depth 10

Write-Host "`n== Latest orchestrator guardrail lines =="
kubectl logs -n $ns deploy/smartops-orchestrator --tail=1500 | Select-String "restart_on_anomaly_error|policy denied execution|blocked|CLOSED_LOOP_SUMMARY"

Write-Host "`n== Latest policy audit =="
kubectl run -n $ns curlpod --image=curlimages/curl:8.5.0 --restart=Never -i --rm -- `
  curl -sS "http://smartops-policy-engine:5051/v1/policy/audit/latest?n=30"

Write-Host "`n== Scenario 3 guardrail cooldown run completed =="
