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

app = FastAPI(title="SmartOps Policy Engine", version="0.3")

# ============================================================
# Paths + defaults
# ============================================================
AUDIT_PATH = Path("apps/policy_engine/audit/policy_decisions.jsonl")
AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Default orchestration target (used unless overridden later)
DEFAULT_TARGET = {
    "kind": "Deployment",
    "namespace": "smartops-dev",
    "name": "smartops-erp-simulator",
}

# ============================================================
# Helper utilities
# ============================================================
def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _audit(event: dict) -> None:
    """
    Append one policy decision to the audit log (JSONL).
    This is critical for:
      - demos
      - debugging
      - PP / viva evidence
    """
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _build_action_plan(chosen, default_target: dict) -> dict:
    """
    Convert a DSL Action into an Orchestrator-compatible ActionPlan.
    """
    if chosen.action.type == "restart":
        return {
            "type": "restart",
            "dry_run": False,
            "verify": True,
            "target": default_target,
        }

    # scale action
    return {
        "type": "scale",
        "dry_run": False,
        "verify": True,
        "target": default_target,
        "scale": {"replicas": chosen.action.replicas},
    }


# ============================================================
# Core evaluation logic
# ============================================================
def _evaluate_once(payload: dict | None = None) -> dict:
    """
    Runs ONE full policy evaluation cycle.

    Correct production execution path:
      Agent Detect  -> latest_detection.json
      RCA Engine    -> latest_rca.json
      Policy Engine -> DSL evaluation + guardrails

    Optional:
      - payload["signal"] can override runtime signal
        (used by Orchestrator or curl for testing)
    """

    # --------------------------------------------------------
    # 1. Load policies (DSL)
    # --------------------------------------------------------
    policies = load_default_policies()

    # --------------------------------------------------------
    # 2. Load runtime signal (PRIMARY SOURCE)
    # --------------------------------------------------------
    signal = load_runtime_signals()

    # --------------------------------------------------------
    # 3. Optional override from request payload
    #    (Payload wins over runtime — controlled & explicit)
    # --------------------------------------------------------
    if payload:
        incoming_signal = payload.get("signal") or {}
        signal.update(incoming_signal)
        signal["raw"]["incoming"] = payload

    # --------------------------------------------------------
    # 4. Anomaly gate (PRODUCTION-CORRECT)
    # --------------------------------------------------------
    # We only act if Agent Detect raised an anomaly
    anomaly_flag = bool(signal["raw"]["detection"].get("anomaly", False))

    if not anomaly_flag:
        decision = {
            "ts_utc": _utc_now(),
            "decision": "no_action",
            "reason": "no active anomaly",
            "signal_summary": {
                "anomaly.type": signal.get("anomaly.type"),
                "rca.cause": signal.get("rca.cause"),
            },
        }
        _audit(decision)
        return decision

    # --------------------------------------------------------
    # 5. Evaluate policies against signal
    # --------------------------------------------------------
    chosen = evaluate_policies(policies, signal)

    if not chosen:
        decision = {
            "ts_utc": _utc_now(),
            "decision": "no_action",
            "reason": "no policy matched",
            "signal_summary": {
                "anomaly.type": signal.get("anomaly.type"),
                "rca.cause": signal.get("rca.cause"),
            },
        }
        _audit(decision)
        return decision

    # --------------------------------------------------------
    # 6. Build action plan + apply guardrails
    # --------------------------------------------------------
    action_plan = _build_action_plan(chosen, DEFAULT_TARGET)
    allowed, reason = apply_guardrails(action_plan)

    decision = {
        "ts_utc": _utc_now(),
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
        },
    }

    _audit(decision)
    return decision


# ============================================================
# API routes
# ============================================================
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/v1/policy/evaluate")
def evaluate(payload: dict = Body(default={})):
    """
    Machine-readable decision endpoint.
    Used by:
      - SmartOps Orchestrator
      - curl / test harness
    """
    return _evaluate_once(payload)


@app.get("/v1/policy/evaluate/report", response_class=PlainTextResponse)
def evaluate_report():
    """
    Human-readable policy decision report
    (lecturer / demo friendly).
    """
    decision = _evaluate_once(None)
    return _to_report_text(decision)


@app.get("/v1/policy/audit/latest")
def audit_latest(n: int = 20):
    """
    Returns last N policy decisions.
    """
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
