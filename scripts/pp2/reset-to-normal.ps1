$ns = "smartops-dev"

Write-Host "== Disable all simulator chaos modes on ALL simulator pods =="

kubectl get pods -n $ns -l app=smartops-erp-simulator -o name | ForEach-Object {
    Write-Host "`n--- $_ ---"
    kubectl exec -n $ns $_ -- python -c "import urllib.request; urls=['http://127.0.0.1:8000/chaos/memory-leak/disable','http://127.0.0.1:8000/chaos/cpu-spike/disable','http://127.0.0.1:8000/chaos/latency-jitter/disable','http://127.0.0.1:8000/chaos/error-burst/disable','http://127.0.0.1:8000/chaos/modes']; [print(urllib.request.urlopen(u, data=b'' if 'disable' in u else None, timeout=5).read().decode()) for u in urls]"
}

Write-Host "`n== Scale ERP simulator back to baseline =="
kubectl scale deploy/smartops-erp-simulator -n $ns --replicas=3
kubectl rollout status deploy/smartops-erp-simulator -n $ns

Write-Host "`n== Reset remediation annotations =="
kubectl annotate deploy/smartops-erp-simulator -n $ns smartops.io/remediation-level="0" --overwrite
kubectl annotate deploy/smartops-erp-simulator -n $ns smartops.io/baseline-replicas="3" --overwrite

Write-Host "`n== Disable all chaos modes again on CURRENT simulator pods after rollout =="
kubectl get pods -n $ns -l app=smartops-erp-simulator -o name | ForEach-Object {
    $podName = $_
    Write-Host "`n--- $podName ---"
    $cleaned = $false

    for ($attempt = 1; $attempt -le 3; $attempt++) {
        kubectl exec -n $ns $podName -- python -c "import urllib.request; urls=['http://127.0.0.1:8000/chaos/memory-leak/disable','http://127.0.0.1:8000/chaos/cpu-spike/disable','http://127.0.0.1:8000/chaos/latency-jitter/disable','http://127.0.0.1:8000/chaos/error-burst/disable','http://127.0.0.1:8000/chaos/modes']; [print(urllib.request.urlopen(u, data=b'' if 'disable' in u else None, timeout=5).read().decode()) for u in urls]" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $cleaned = $true
            break
        }

        Write-Host "Attempt $attempt failed for $podName, waiting for pod readiness..."
        Start-Sleep -Seconds 3
    }

    if (-not $cleaned) {
        Write-Host "Skipping $podName after retries; continuing reset."
    }
}

Write-Host "`n== Force detector into PP2 stable mode =="
kubectl set env deploy/smartops-agent-detect-sim -n $ns ISO_ENABLED=0 SIM_USE_GROUND_TRUTH=1
kubectl rollout restart deploy/smartops-agent-detect-sim -n $ns
kubectl rollout status deploy/smartops-agent-detect-sim -n $ns

Write-Host "`n== Current deployment state =="
kubectl get deploy smartops-erp-simulator -n $ns -o jsonpath="{.spec.replicas}{' '}{.status.readyReplicas}{' '}{.metadata.annotations.smartops\.io/baseline-replicas}{' '}{.metadata.annotations.smartops\.io/remediation-level}"
Write-Host ""

Write-Host "`n== Detector status (first check) =="
kubectl logs -n $ns deploy/smartops-agent-detect-sim --tail=80

Write-Host "`n== Detector status (second check, latest pod state) =="
kubectl logs -n $ns deploy/smartops-agent-detect-sim --tail=40

Write-Host "`n== Latest anomaly lines from orchestrator =="
kubectl logs -n $ns deploy/smartops-orchestrator --tail=250 | Select-String "SIGNAL_RAW | kind=anomaly"