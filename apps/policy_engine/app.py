from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from apps.policy_engine.repository.policy_store import load_default_policies
from apps.policy_engine.runtime.adapter import load_runtime_signals
from apps.policy_engine.runtime.evaluator import evaluate_policies
from apps.policy_engine.runtime.guardrails import apply_guardrails

app = FastAPI(title="SmartOps Policy Engine", version="0.2")

# -----------------------------
# Paths + defaults
# -----------------------------
AUDIT_PATH = Path("apps/policy_engine/audit/policy_decisions.jsonl")
AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Adjust these to your real k8s target (MVP defaults)
DEFAULT_TARGET = {
    "kind": "Deployment",
    "namespace": "smartops-dev",
    "name": "erp-simulator",
}


# -----------------------------
# Helpers
# -----------------------------
def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _audit(event: dict) -> None:
    """
    Append a single JSON line event to the audit log.
    WHY: We need traceability for demos, debugging, and PP evidence.
    """
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _build_action_plan(chosen, default_target: dict) -> dict:
    """
    Convert chosen policy action → orchestrator ActionPlan (MVP shape)
    """
    if chosen.action.type == "restart":
        return {
            "type": "restart",
            "dry_run": False,
            "verify": True,
            "target": default_target,
        }

    # scale
    return {
        "type": "scale",
        "dry_run": False,
        "verify": True,
        "target": default_target,
        "scale": {"replicas": chosen.action.replicas},
    }


def _to_report_text(decision: dict) -> str:
    """
    Convert decision JSON → pretty human-readable report.
    WHY: Lecturers prefer readable reports in demos (like RCA output).
    """
    lines: List[str] = []
    lines.append("")
    lines.append("===== POLICY ENGINE DECISION REPORT =====")
    lines.append(f"Time (UTC):        {decision.get('ts_utc', 'N/A')}")
    lines.append(f"Decision:          {decision.get('decision', 'N/A')}")

    if decision.get("decision") == "no_action":
        lines.append(f"Reason:            {decision.get('reason', 'N/A')}")
        sig = decision.get("signal_summary") or {}
        if sig:
            lines.append("")
            lines.append("Signal Summary:")
            for k, v in sig.items():
                lines.append(f"  - {k}: {v}")
        lines.append("=========================================")
        lines.append("")
        return "\n".join(lines)

    # action / blocked
    lines.append(f"Policy:            {decision.get('policy', 'N/A')}")
    lines.append(f"Priority:          {decision.get('priority', 'N/A')}")
    lines.append(f"Guardrail Reason:  {decision.get('guardrail_reason', 'N/A')}")

    ap = decision.get("action_plan")
    if ap:
        lines.append(f"Action Type:       {ap.get('type', 'N/A')}")
        lines.append(f"Dry Run:           {ap.get('dry_run', 'N/A')}")
        lines.append(f"Verify:            {ap.get('verify', 'N/A')}")

        tgt = ap.get("target") or {}
        if tgt:
            lines.append(
                f"Target:            {tgt.get('kind','?')} / {tgt.get('namespace','?')} / {tgt.get('name','?')}"
            )

        if ap.get("type") == "scale":
            scale = ap.get("scale") or {}
            lines.append(f"Scale Replicas:    {scale.get('replicas', 'N/A')}")

    sig = decision.get("signal_summary") or {}
    if sig:
        lines.append("")
        lines.append("Signal Summary:")
        for k, v in sig.items():
            lines.append(f"  - {k}: {v}")

    lines.append("=========================================")
    lines.append("")
    return "\n".join(lines)


def _evaluate_once() -> dict:
    """
    Runs the full evaluation once and returns the decision dict.
    Shared by /v1/policy/evaluate and /v1/policy/evaluate/report.
    """
    policies = load_default_policies()
    signal = load_runtime_signals()

    # Gate by detection flag
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


# -----------------------------
# Routes
# -----------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/v1/policy/evaluate")
def evaluate():
    """
    Machine-readable JSON decision for orchestration.
    """
    return _evaluate_once()


@app.get("/v1/policy/evaluate/report", response_class=PlainTextResponse)
def evaluate_report():
    """
    Human-readable text report (lecturer/demo friendly).
    """
    decision = _evaluate_once()
    return _to_report_text(decision)


@app.get("/v1/policy/audit/latest")
def audit_latest(n: int = 20):
    """
    Returns last N audit events.
    WHY: Quick demo/debug without opening the jsonl file manually.
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
            # If an invalid line exists, skip it
            continue

    return {"ok": True, "returned": len(events), "events": events}
