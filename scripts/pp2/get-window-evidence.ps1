param(
    [Parameter(Mandatory=$true)]
    [string]$WindowId
)

$ns = "smartops-dev"

Write-Host "== Orchestrator lines for windowId=$WindowId =="
kubectl logs -n $ns deploy/smartops-orchestrator --tail=1500 | Select-String -Pattern $WindowId

Write-Host "`n== Anomaly lines =="
kubectl logs -n $ns deploy/smartops-orchestrator --tail=1500 | Select-String "SIGNAL_RAW | kind=anomaly" | Select-String -Pattern $WindowId

Write-Host "`n== RCA lines =="
kubectl logs -n $ns deploy/smartops-orchestrator --tail=1500 | Select-String "SIGNAL_RAW | kind=rca" | Select-String -Pattern $WindowId

Write-Host "`n== Closed-loop summary lines =="
kubectl logs -n $ns deploy/smartops-orchestrator --tail=1500 | Select-String "CLOSED_LOOP_SUMMARY" | Select-String -Pattern $WindowId

Write-Host "`n== Policy audit (latest events) =="
kubectl run -n $ns curlpod --image=curlimages/curl:8.5.0 --restart=Never -i --rm -- `
  curl -sS "http://smartops-policy-engine:5051/v1/policy/audit/latest?n=30"

Write-Host "`n== Current deployment state =="
kubectl get deploy smartops-erp-simulator -n $ns -o jsonpath="{.spec.replicas}{' '}{.status.readyReplicas}{' '}{.metadata.annotations.smartops\.io/baseline-replicas}{' '}{.metadata.annotations.smartops\.io/remediation-level}"
Write-Host ""

Write-Host "`n== Detector status snapshot =="
kubectl logs -n $ns deploy/smartops-agent-detect-sim --tail=40