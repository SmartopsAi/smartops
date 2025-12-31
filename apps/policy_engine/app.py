from fastapi import FastAPI
from apps.policy_engine.repository.policy_store import load_default_policies
from apps.policy_engine.runtime.adapter import load_runtime_signals
from apps.policy_engine.runtime.evaluator import evaluate_policies
from apps.policy_engine.runtime.guardrails import apply_guardrails
from pathlib import Path
import json
from datetime import datetime

app = FastAPI(title="SmartOps Policy Engine", version="0.1")

AUDIT_PATH = Path("apps/policy_engine/audit/policy_decisions.jsonl")
AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Adjust these to your real k8s target (MVP defaults)
DEFAULT_TARGET = {
    "kind": "Deployment",
    "namespace": "smartops-dev",
    "name": "erp-simulator"
}

def _audit(event: dict):
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")

@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.post("/v1/policy/evaluate")
def evaluate():
    policies = load_default_policies()
    signal = load_runtime_signals()

    # if no anomaly, return no_action
    anomaly_flag = bool(signal["raw"]["detection"].get("anomaly", False))
    if not anomaly_flag:
        decision = {
            "ts_utc": datetime.utcnow().isoformat() + "Z",
            "decision": "no_action",
            "reason": "no active anomaly",
            "signal_summary": {
                "anomaly.type": signal.get("anomaly.type"),
                "rca.cause": signal.get("rca.cause"),
            }
        }
        _audit(decision)
        return decision

    chosen = evaluate_policies(policies, signal)

    if not chosen:
        decision = {
            "ts_utc": datetime.utcnow().isoformat() + "Z",
            "decision": "no_action",
            "reason": "no policy matched",
            "signal_summary": {
                "anomaly.type": signal.get("anomaly.type"),
                "rca.cause": signal.get("rca.cause"),
            }
        }
        _audit(decision)
        return decision

    # compile policy action -> orchestrator ActionPlan shape (MVP)
    if chosen.action.type == "restart":
        action_plan = {
            "type": "restart",
            "dry_run": False,
            "verify": True,
            "target": DEFAULT_TARGET
        }
    else:
        action_plan = {
            "type": "scale",
            "dry_run": False,
            "verify": True,
            "target": DEFAULT_TARGET,
            "scale": {"replicas": chosen.action.replicas}
        }

    allowed, reason = apply_guardrails(action_plan)

    decision = {
        "ts_utc": datetime.utcnow().isoformat() + "Z",
        "decision": "action" if allowed else "blocked",
        "policy": chosen.name,
        "priority": chosen.priority,
        "guardrail_reason": reason,
        "action_plan": action_plan if allowed else None,
        "signal_summary": {
            "anomaly.type": signal.get("anomaly.type"),
            "anomaly.score": signal.get("anomaly.score"),
            "rca.cause": signal.get("rca.cause"),
            "rca.probability": signal.get("rca.probability"),
        }
    }
    _audit(decision)
    return decision
