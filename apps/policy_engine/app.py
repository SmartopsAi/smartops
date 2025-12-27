from __future__ import annotations

import os
import uuid
from typing import Union

from fastapi import FastAPI, Query

from apps.policy_engine.schemas.models import (
    AnomalySignal,
    RcaSignal,
    ActionPlan,
    PolicyValidateRequest,
    PolicyValidateResponse,
    PolicyStatusResponse,
    PolicyReloadResponse,
    PolicyAuditResponse,
    PolicyAuditEvent,
)

from apps.policy_engine.dsl.parser import parse_policies
from apps.policy_engine.runtime.policy_store import PolicyStore
from apps.policy_engine.runtime.evaluator import evaluate_signal_with_policies, get_policy_status
from apps.policy_engine.runtime.audit_logger import AuditLogger


def _default_policy_path() -> str:
    """
    WHY:
    - Use your existing policy file location (repository/default.policy)
    - Avoid moving files and breaking anything old
    - Still allows override via POLICY_FILE env var
    """
    return os.getenv(
        "POLICY_FILE",
        os.path.join(os.path.dirname(__file__), "repository", "default.policy"),
    )


def _audit_log_path() -> str:
    """
    WHY:
    - Stable location inside the policy_engine module
    - Easy to find for demo + report
    """
    return os.getenv(
        "AUDIT_LOG_FILE",
        os.path.join(os.path.dirname(__file__), "audit", "policy_decisions.jsonl"),
    )


app = FastAPI(title="SmartOps Policy Engine", version="0.4.0")

policy_store = PolicyStore(policy_path=_default_policy_path())
audit_logger = AuditLogger(log_path=_audit_log_path())


@app.on_event("startup")
def _startup_load_policies():
    result = policy_store.load_initial()
    if not result.ok:
        print(f"[policy_engine] WARNING: initial policy load failed: {result.error}")
    else:
        print(f"[policy_engine] loaded {result.policy_count} policies from {result.source_path}")
        print(f"[policy_engine] audit log file: {_audit_log_path()}")


@app.get("/healthz")
def health_check():
    return {"status": "ok", "service": "policy-engine"}


@app.post("/v1/policy/reload", response_model=PolicyReloadResponse)
def reload_policies():
    result = policy_store.reload()
    return PolicyReloadResponse(
        ok=result.ok,
        policy_count=result.policy_count,
        source_path=result.source_path,
        error=result.error,
    )


@app.post("/v1/policy/evaluate", response_model=ActionPlan)
def evaluate_policy(signal: Union[AnomalySignal, RcaSignal]):
    """
    WHY (STEP 8):
    - Evaluate using in-memory policies
    - Create audit event for each decision
    - Persist audit event to JSONL file
    """
    policies = policy_store.get_policies()
    request_id = str(uuid.uuid4())

    plan, audit_event = evaluate_signal_with_policies(
        signal,
        policies,
        _default_policy_path(),
        request_id,
    )

    try:
        audit_logger.write_event(audit_event)
    except Exception as e:
        print(f"[policy_engine] WARNING: failed to write audit log: {e}")

    return plan

            #---- Audit api part ------

@app.get("/v1/policy/audit", response_model=PolicyAuditResponse)
def get_audit_logs(limit: int = Query(default=20, ge=1, le=200)):
    """
    WHY:
    - Lets us view policy decisions through an API (for demo, debugging, report)
    - limit controls how many latest events to return
    """
    try:
        events = audit_logger.read_last_events(limit=limit)
        return PolicyAuditResponse(
            ok=True,
            log_path=_audit_log_path(),
            returned=len(events),
            events=[PolicyAuditEvent(event=e) for e in events],
            error=None,
        )
    except Exception as e:
        return PolicyAuditResponse(
            ok=False,
            log_path=_audit_log_path(),
            returned=0,
            events=[],
            error=str(e),
        )


@app.post("/v1/policy/validate", response_model=PolicyValidateResponse)
def validate_policy(req: PolicyValidateRequest):
    dsl_text = (req.dsl or "").strip()
    if not dsl_text:
        return PolicyValidateResponse(valid=False, policy_count=0, errors=["DSL text is empty."])

    try:
        policies = parse_policies(dsl_text)
        return PolicyValidateResponse(valid=True, policy_count=len(policies), errors=[])
    except Exception as e:
        return PolicyValidateResponse(valid=False, policy_count=0, errors=[str(e)])


@app.get("/v1/policy/status", response_model=PolicyStatusResponse)
def policy_status():
    policies = policy_store.get_policies()
    return get_policy_status(policies, policy_file_path=_default_policy_path())
