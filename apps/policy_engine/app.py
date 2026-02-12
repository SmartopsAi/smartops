from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import FastAPI, Body
from fastapi.responses import PlainTextResponse

from apps.policy_engine.repository.policy_store import load_default_policies
from apps.policy_engine.runtime.adapter import load_runtime_signals
from apps.policy_engine.runtime.evaluator import evaluate_policies
from apps.policy_engine.runtime.guardrails import apply_guardrails

app = FastAPI(title="SmartOps Policy Engine", version="0.4")

# ============================================================
# Paths + defaults
# ============================================================
AUDIT_PATH = Path("apps/policy_engine/audit/policy_decisions.jsonl")
AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------
# Service → Kubernetes target mapping (CRITICAL FIX)
# ------------------------------------------------------------
SERVICE_TARGETS = {
    "erp-simulator": {
        "kind": "Deployment",
        "namespace": "smartops-dev",
        "name": "smartops-erp-simulator",
    },
    "odoo": {
        "kind": "Deployment",
        "namespace": "smartops-dev",
        "name": "odoo-web",
    },
}

# ============================================================
# Utilities
# ============================================================
def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _audit(event: dict) -> None:
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _resolve_target(signal: dict) -> dict:
    service_name = signal.get("service") or signal["raw"].get("incoming", {}).get("service")
    return SERVICE_TARGETS.get(service_name, SERVICE_TARGETS["erp-simulator"])


def _build_action_plan(chosen, signal: dict) -> dict:
    target = _resolve_target(signal)

    if chosen.action.type == "restart":
        return {
            "type": "restart",
            "dry_run": False,
            "verify": True,
            "target": target,
        }

    return {
        "type": "scale",
        "dry_run": False,
        "verify": True,
        "target": target,
        "scale": {"replicas": chosen.action.replicas},
    }


# ============================================================
# Core evaluation logic
# ============================================================
def _evaluate_once(payload: dict | None = None) -> dict:
    policies = load_default_policies()
    signal = load_runtime_signals()

    if payload:
        incoming_signal = payload.get("signal") or {}
        signal.update(incoming_signal)
        signal["raw"]["incoming"] = payload

    anomaly_flag = bool(signal["raw"]["detection"].get("anomaly", False))

    if not anomaly_flag:
        decision = {
            "ts_utc": _utc_now(),
            "decision": "no_action",
            "reason": "no active anomaly",
        }
        _audit(decision)
        return decision

    chosen = evaluate_policies(policies, signal)

    if not chosen:
        decision = {
            "ts_utc": _utc_now(),
            "decision": "no_action",
            "reason": "no policy matched",
        }
        _audit(decision)
        return decision

    action_plan = _build_action_plan(chosen, signal)
    allowed, reason = apply_guardrails(action_plan)

    decision = {
        "ts_utc": _utc_now(),
        "decision": "action" if allowed else "blocked",
        "policy": chosen.name,
        "priority": chosen.priority,
        "guardrail_reason": reason,
        "action_plan": action_plan if allowed else None,
    }

    _audit(decision)
    return decision


# ============================================================
# API
# ============================================================
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/v1/policy/evaluate")
def evaluate(payload: dict = Body(default={})):
    return _evaluate_once(payload)


@app.get("/v1/policy/audit/latest")
def audit_latest(n: int = 20):
    if not AUDIT_PATH.exists():
        return {"ok": True, "events": []}

    lines = AUDIT_PATH.read_text(encoding="utf-8").splitlines()
    tail = lines[-max(1, n):]

    events = []
    for ln in tail:
        try:
            events.append(json.loads(ln))
        except Exception:
            continue

    return {"ok": True, "returned": len(events), "events": events}
