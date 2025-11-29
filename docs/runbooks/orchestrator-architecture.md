# SmartOps Orchestrator — Architecture & Design

## 1. Role in SmartOps

The Orchestrator is the **central control plane** for runtime actions on the ERP on Kubernetes.

It is responsible for:

- Executing **Kubernetes actions** (scale, restart, patch).
- Providing a **uniform REST API** for other SmartOps components.
- Running the **closed-loop controller** that consumes anomaly/RCA signals and triggers remediation.
- Emitting **metrics and traces** for observability.
- Enforcing **guardrails** so automation stays safe.

It lives in the namespace:

- `smartops-dev` (dev environment; configured via `global.smartops.namespace` in Helm).

---

## 2. Key Components

### 2.1 FastAPI Application (`apps/orchestrator/app.py`)

- Exposes health, metrics, and action endpoints:
  - `GET /healthz`
  - `GET /metrics`
  - `POST /v1/k8s/scale`
  - `POST /v1/k8s/restart`
  - `POST /v1/k8s/patch`
  - `POST /v1/actions/execute`
  - `POST /v1/signals/anomaly`
  - `POST /v1/signals/rca`

- Wires routers and services:
  - `orchestrator_service` for direct actions.
  - `closed_loop_manager` for signal ingestion.

### 2.2 Kubernetes Core Wrapper (`apps/orchestrator/services/k8s_core.py`)

Thin wrapper around the Kubernetes Python client, providing:

- Pod operations:
  - `list_pods()`
  - `delete_pod()`
- Deployment operations:
  - `list_deployments()`
  - `get_deployment_status()`
  - `scale_deployment()`
  - `restart_deployment()` (rollout restart via annotation)
  - `patch_deployment()`
  - `wait_for_deployment_rollout()`

Metrics:

- `smartops_k8s_api_calls_total`
- `smartops_k8s_api_errors_total`
- `smartops_k8s_api_latency_seconds`
- `smartops_k8s_scale_total`
- `smartops_k8s_restart_total`
- `smartops_k8s_patch_total`
- `smartops_k8s_deployment_desired_replicas`
- `smartops_k8s_deployment_ready_replicas`

### 2.3 Kubernetes Client Helper (`apps/orchestrator/utils/k8s_client.py`)

- Loads in-cluster config by default (`ServiceAccount`).
- Falls back to local kubeconfig for dev on laptop.
- Returns `CoreV1Api` and `AppsV1Api` to the rest of the code.

### 2.4 Closed-loop Controller (`apps/orchestrator/services/closed_loop.py`)

Responsibilities:

- Maintains an **async queue** of `QueueItem` (anomaly or RCA signals).
- Maps signals → `ActionRequest` using:
  - `AnomalySignal` (resource, latency, error, other)
  - `RcaSignal` (rankedCauses, confidence)
- Applies:
  - **Cooldowns** per (namespace, deployment, actionType).
  - **Guardrails**:
    - Max replicas.
    - Max actions per hour.
    - Max scale increase in 15 minutes.
    - Replica guardrails propagated as HTTP exceptions from Orchestrator.
- Executes actions using `orchestrator_service.execute_action()`.
- Waits for rollout verification via `verification_service`.
- Handles retries with exponential backoff.

Key metrics:

- `orchestrator_closed_loop_signals_total`
- `orchestrator_closed_loop_actions_total`
- `orchestrator_closed_loop_retries_total`
- `orchestrator_closed_loop_duration_seconds`
- `orchestrator_closed_loop_action_duration_seconds`
- `orchestrator_closed_loop_queue_depth`
- `orchestrator_closed_loop_guardrail_blocks_total`

### 2.5 Verification Service (`apps/orchestrator/services/verification_service.py`)

- Performs **deployment rollout verification** asynchronously.
- Uses `k8s_core.get_deployment_status()` and `k8s_core.wait_for_deployment_rollout()` in a thread pool.
- Returns `DeploymentVerificationResult` with:
  - `status` → `SUCCESS`, `TIMED_OUT`, or `FAILED`.
  - Desired vs ready vs available replicas.
  - Last observed rollout status.

### 2.6 Action Models & Requests (`apps/orchestrator/models/*.py`)

- `ActionRequest`:
  - `type` → `SCALE`, `RESTART`, `PATCH`, etc.
  - `target` → `K8sTarget(kind="Deployment", namespace, name)`.
  - Optional `scale`, `patch`, `reason`, `dry_run`, `verify`.
- `VerificationStatus` enum and result models.

---

## 3. Request Flows

### 3.1 Direct Action (Human or Policy Engine)

Example: scale ERP deployment.

1. Client calls:

   ```http
   POST /v1/k8s/scale
   {
     "deployment": "erp-simulator",
     "replicas": 3,
     "namespace": "smartops-dev",
     "dry_run": false
   }
FastAPI layer parses the request → ActionRequest.

(Future) policy_client.check_policy() will be invoked.

orchestrator_service calls k8s_core.scale_deployment().

Optionally, verification_service.verify_deployment_rollout() is called.

Response includes:

success

message

dry_run

details.runner

verification (if enabled)

3.2 Closed-loop from Anomaly Signal
Agent sends anomaly:

http
Copy code
POST /v1/signals/anomaly
{
  "windowId": "win-123",
  "service": "erp-simulator",
  "isAnomaly": true,
  "score": 0.95,
  "type": "resource",
  "metadata": { "cpu": 96.3 }
}
API enqueues an AnomalySignal into closed_loop_manager.queue.

Worker picks up the signal:

Maps to ActionRequest (e.g., SCALE +1 replica).

Checks cooldown and guardrails.

Calls execute_action().

Calls verify_deployment_rollout().

Metrics:

orchestrator_closed_loop_signals_total{kind="anomaly"}

orchestrator_closed_loop_actions_total{type="scale", status="success"}

orchestrator_closed_loop_duration_seconds

3.3 Closed-loop from RCA Signal
Agent sends RCA:

http
Copy code
POST /v1/signals/rca
{
  "windowId": "win-xxx",
  "rankedCauses": [
    { "svc": "erp-simulator", "cause": "memory_leak", "probability": 0.93 }
  ],
  "confidence": 0.93
}
ClosedLoopManager maps:

"memory_leak" → RESTART action.

Same execution/verification pipeline as above.

4. Guardrails
4.1 Replica Guardrails
Enforced at orchestrator level (HTTP 400) and closed-loop level.

Limit:

Maximum replicas per deployment (default 8 in dev).

4.2 Rate Guardrails (Closed-loop)
Max actions per hour per (namespace, deployment, type):

Default: 6.

Prevents action storms for a single workload.

Max scale increase in 15 minutes per deployment:

Default: +3 replicas.

Prevents runaway scaling from noisy anomalies.

4.3 Cooldown
Per (namespace, deployment, type), default 300 seconds.

Ensures enough time for effects to propagate before the next action.

5. RBAC & Security
5.1 Service Account & RBAC
Files:

platform/helm/smartops/templates/orchestrator-rbac.yaml

platform/helm/smartops/templates/orchestrator-deployment.yaml

The Orchestrator runs as:

ServiceAccount: smartops-orchestrator in smartops-dev.

Permissions (Role):

Pods/logs/events:

get, list, watch, delete

Deployments/ReplicaSets:

get, list, watch, patch, update

Deployment scale subresource:

get, list, watch, patch, update

Namespaces:

get, list

5.2 Network & Telemetry
Orchestrator exposes:

HTTP service on ClusterIP (smartops-orchestrator).

OTEL exporter:

OTEL_EXPORTER_OTLP_ENDPOINT = http://smartops-otelcol:4317

Traces sent to Tempo via OTEL Collector.

6. Observability
6.1 Metrics
Exposed via /metrics on the Orchestrator service.

Scraped by Prometheus (kube-prometheus-stack).

Dashboard:

smartops-system-dashboard (ConfigMap, auto-loaded by Grafana).

6.2 Traces
Instrumented with OpenTelemetry (FastAPI, k8s calls, closed-loop).

Sent to OTEL Collector → Tempo.

Grafana has:

Tempo datasource.

Prometheus datasource.

Service map possible via Tempo + Prom.

7. Future: Policy Engine Integration
Planned flow (once Policy Engine exists):

Client or Closed Loop proposes ActionRequest.

Orchestrator calls policy_client.check_policy(action):

Sends action + context + signal metadata to Policy Engine.

Receives allow/deny with reason.

If denied:

Orchestrator returns 403 with reason.

Metrics incremented (e.g., smartops_orchestrator_policy_denials_total).

This keeps all runtime decisions auditable and separates policy from mechanism.

8. Summary
The Orchestrator is now:

API-complete for Kubernetes actions.

Integrated with telemetry (Prometheus + OTEL).

Protected with RBAC in smartops-dev.

Guardrail-aware, with:

Cooldowns

Replica limits

Rate limits

Scale-velocity limits

Closed-loop ready, consuming anomaly & RCA signals and verifying rollouts.