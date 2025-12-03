
# 📘 **Runbook: Orchestrator RBAC & Guardrails – SmartOps**

**Owner:** Peiris P.V.G (IT22364388)
**Component:** SmartOps Orchestrator
**Environment:** `smartops-dev`
**Last Updated:** 2025-11-29

---

## Overview

This runbook documents the Kubernetes RBAC permissions and Guardrail controls for the SmartOps Orchestrator component. It ensures safe execution of scaling, restarting, and patching actions triggered by the Policy Engine, Closed-Loop Manager, or manual operator API calls.

The orchestrator operates under the **ServiceAccount: `smartops-orchestrator`**, scoped strictly to the namespace `smartops-dev`.

---

# 1. Kubernetes RBAC Permissions

The RBAC configuration is intentionally minimal and secure.
The orchestrator is allowed only the operations required for cluster remediation.

### ✔ Allowed Operations

| Resource         | Verbs                           | Reason                                                         |
| ---------------- | ------------------------------- | -------------------------------------------------------------- |
| Pods             | get, list, watch, **delete**    | Needed for rolling restarts, pod-kill chaos, stale pod cleanup |
| Pod logs         | get, list                       | For verification & debugging                                   |
| Events           | get, list, watch                | For rollout verification                                       |
| Deployments      | get, list, watch, patch, update | Required for restart + patch                                   |
| Deployment/scale | patch, update                   | Required for scaling                                           |
| ReplicaSets      | get, list, watch                | Deployment rollout checks                                      |
| Namespace        | get, list                       | Context discovery only                                         |

### ✔ Denied by Design

* No ability to create deployments
* No ability to delete deployments
* No ability to modify cluster-wide objects
* No node-level access
* No CRD access
* No cross-namespace operations
* No secrets access

---

# 2. How Orchestrator Uses RBAC

### **Restarts**

Uses `patch` on deployment template annotation + `delete` on pods.

### **Scaling**

Uses the `/scale` subresource (`apps/v1`).

### **Verification**

Uses:

* `get deployment`
* `watch deployment`
* `list deployments`
* `list pods`
* `list events`

### **Closed-Loop Manager**

RBAC ensures the closed loop **cannot escalate privileges** or perform dangerous actions.

---

# 3. Guardrails

Guardrails are implemented at the Orchestrator API level, not via RBAC.

### Guardrails Prevent:

* Downscaling below minimum replica threshold
* Upscaling beyond safe maximum limit
* Restart storms (cooldown enforced)
* Patch attempts outside an allowed whitelist
* Actions triggered too frequently

### Interaction With RBAC

| Condition                               | Guardrail                  | RBAC                                       | Final Behavior           |
| --------------------------------------- | -------------------------- | ------------------------------------------ | ------------------------ |
| Policy tries to delete Deployment       | ❌ blocked                  | Would also fail by RBAC                    | Guardrail fails first    |
| Policy tries to patch disallowed fields | ❌ blocked                  | Would fail if touching forbidden resources | Guardrail logs + rejects |
| Closed loop tries restart too soon      | ❌ cooldown-blocked         | RBAC irrelevant                            | No API call made         |
| Action attempts cross-namespace op      | ❌ Guardrail OR RBAC blocks | RBAC denies                                | Error surfaced to caller |

Guardrails = application-level safety
RBAC = cluster-level enforceable boundary

---

# 4. Deployment Structure

Orchestrator Deployment uses:

```yaml
serviceAccountName: smartops-orchestrator
```

and inherits namespace automatically using:

```yaml
env:
  - name: K8S_NAMESPACE
    valueFrom:
      fieldRef:
        fieldPath: metadata.namespace
```

The orchestrator is permanently pinned to the namespace it runs in.
It **cannot** act outside that namespace.

---

# 5. Verification & Debugging

### 🧪 Validate RBAC After Deployment

```bash
kubectl auth can-i get pod --as=system:serviceaccount:smartops-dev:smartops-orchestrator -n smartops-dev
kubectl auth can-i delete pod --as=system:serviceaccount:smartops-dev:smartops-orchestrator -n smartops-dev
kubectl auth can-i patch deployment --as=system:serviceaccount:smartops-dev:smartops-orchestrator -n smartops-dev
kubectl auth can-i patch deployment/scale --as=system:serviceaccount:smartops-dev:smartops-orchestrator -n smartops-dev
```

### 🧪 Verify Orchestrator Restart Capability

```bash
curl -X POST http://orchestrator/v1/k8s/restart \
  -d '{"deployment": "erp-simulator"}'
```

### 🧪 Verify Guardrail Block

Try scaling below 1 replica:

```bash
curl -X POST /v1/k8s/scale -d '{"replicas": 0}'
```

You should receive:

```
Replica guardrail violated
```

---

# 6. Troubleshooting

### 🔴 Error: `forbidden`

RBAC blocked a missing permission.

Fix: check `orchestrator-rbac.yaml`.

---

### 🔴 Error: `guardrail violation`

Orchestrator rejected unsafe action.

Fix: adjust Policy Engine logic or tune guardrail settings.

---

### 🔴 Error: rollout timeout

Deployment failed to reconcile.

Fix: check:

```
kubectl describe deployment smartops-erp-simulator
kubectl get pods -l app=erp-simulator
kubectl get events
```

---

# 7. Security Notes

* Orchestrator remains namespace-scoped deliberately.
* ServiceAccount must never have cluster-admin or wildcard verbs.
* Orchestrator must NEVER obtain secret read access.
* Only replicas, pods, events, deployments may be touched.

---

# ✔ Conclusion

By applying:

1. RBAC update (done)
2. RBAC validation (done)
3. CRD check (done)
4. Runbook creation (provided above)

