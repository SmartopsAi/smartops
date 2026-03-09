$ns = "smartops-dev"

Write-Host "== Pre-check: deployment state =="
kubectl get deploy smartops-erp-simulator -n $ns -o jsonpath="{.spec.replicas}{' '}{.status.readyReplicas}{' '}{.metadata.annotations.smartops\.io/baseline-replicas}{' '}{.metadata.annotations.smartops\.io/remediation-level}"
Write-Host ""

Write-Host "`n== Pre-check: detector should already be normal =="
kubectl logs -n $ns deploy/smartops-agent-detect-sim --tail=30

Write-Host "`n== Enable CPU spike on ALL simulator pods =="
kubectl get pods -n $ns -l app=smartops-erp-simulator -o name | ForEach-Object {
    kubectl exec -n $ns $_ -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/chaos/cpu-spike/enable', data=b'', timeout=5).read().decode()); print(urllib.request.urlopen('http://127.0.0.1:8000/chaos/modes', timeout=5).read().decode())"
}

Write-Host "`n== Generate traffic =="
kubectl delete pod loadgen -n $ns --ignore-not-found

@'
apiVersion: v1
kind: Pod
metadata:
  name: loadgen
  namespace: smartops-dev
spec:
  restartPolicy: Never
  containers:
    - name: curl
      image: curlimages/curl:8.5.0
      command: ["/bin/sh", "-c"]
      args:
        - |
          i=1
          while [ $i -le 20 ]; do
            curl -s -o /dev/null -w "%{http_code}\n" \
              -X POST http://smartops-erp-simulator:8000/simulate/load \
              -H 'Content-Type: application/json' \
              -d '{"duration_seconds":0.2,"target":"cpu"}'
            i=$((i+1))
            sleep 1
          done
'@ | Set-Content .\loadgen-pod.yaml

kubectl apply -f .\loadgen-pod.yaml

Write-Host "`n== Wait for loadgen pod to complete =="
kubectl wait --for=condition=Ready pod/loadgen -n $ns --timeout=60s

Write-Host "`n== Load generation responses =="
kubectl logs -n $ns loadgen

Write-Host "`n== Detector status after CPU spike traffic =="
kubectl logs -n $ns deploy/smartops-agent-detect-sim --tail=80

Write-Host "`n== Latest anomaly signal =="
kubectl logs -n $ns deploy/smartops-orchestrator --tail=500 | Select-String "SIGNAL_RAW | kind=anomaly"

Write-Host "`n== Latest closed-loop summary =="
kubectl logs -n $ns deploy/smartops-orchestrator --tail=500 | Select-String "CLOSED_LOOP_SUMMARY"

Write-Host "`n== Current deployment state =="
kubectl get deploy smartops-erp-simulator -n $ns -o jsonpath="{.spec.replicas}{' '}{.status.readyReplicas}{' '}{.metadata.annotations.smartops\.io/baseline-replicas}{' '}{.metadata.annotations.smartops\.io/remediation-level}"
Write-Host ""

Write-Host "`n== Latest policy audit =="
kubectl run -n $ns curlpod --image=curlimages/curl:8.5.0 --restart=Never -i --rm -- `
  curl -sS "http://smartops-policy-engine:5051/v1/policy/audit/latest?n=12"