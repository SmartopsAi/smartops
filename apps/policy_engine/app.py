from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from apps.policy_engine.repository.json_policy_repository import (
    PolicyRepositoryError,
    create_policy,
    disable_policy,
    enable_policy,
    get_policy_definition,
    list_change_audit,
    list_policy_definitions,
    reload_policies,
    soft_delete_policy,
    update_policy,
)
from apps.policy_engine.runtime.adapter import load_runtime_signals
from apps.policy_engine.runtime.evaluator import evaluate_policies
from apps.policy_engine.runtime.guardrails import apply_guardrails
from apps.policy_engine.runtime.policy_loader import load_runtime_policies
from apps.policy_engine.runtime.priority_matrix import calculate_priority
from apps.policy_engine.runtime.policy_validator import validate_policy_dsl
from apps.policy_engine.security import require_admin_key

app = FastAPI(title="SmartOps Policy Engine", version="0.5")

# ============================================================
# Paths + defaults
# ============================================================
AUDIT_PATH = Path(os.getenv("POLICY_ENGINE_AUDIT_PATH", "/policy_engine/audit/policy_decisions.jsonl"))
AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)

# ============================================================
# Service â†’ Kubernetes target mapping
# ============================================================
SMARTOPS_NAMESPACE = os.getenv("SMARTOPS_NAMESPACE", "smartops-dev")

SERVICE_TARGETS = {
    "erp-simulator": {
        "kind": "Deployment",
        "namespace": SMARTOPS_NAMESPACE,
        "name": "smartops-erp-simulator",
    },
    "odoo": {
        "kind": "Deployment",
        "namespace": SMARTOPS_NAMESPACE,
        "name": "odoo-web",
    },
}

# ============================================================
# Utilities
# ============================================================
def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _audit(event: dict) -> None:
    try:
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        # Audit must never break evaluation
        pass


def _resolve_target(signal: dict) -> dict:
    # service can exist at top-level or inside raw.incoming.service
    raw = signal.get("raw") or {}
    incoming = raw.get("incoming") or {}
    service_name = signal.get("service") or incoming.get("service") or "erp-simulator"
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


def _set_anomaly_active(signal: dict) -> None:
    """Ensure raw.detection.anomaly is True (for external evaluate calls)."""
    signal.setdefault("raw", {})
    signal["raw"].setdefault("detection", {})
    signal["raw"]["detection"]["anomaly"] = True


def _normalize_signal(signal: dict) -> None:
    """
    Normalize multiple payload styles into one canonical structure that the DSL expects.

    Supported inputs:
      A) Flattened keys:
         - anomaly.type, anomaly.score
         - k8s.replicas.current

      B) Nested keys:
         - anomaly: {type, score}
         - k8s: {replicas: {current}}

    Output:
      signal['anomaly']['type'], signal['anomaly']['score']
      signal['k8s']['replicas']['current']
    """
    # --- Flattened anomaly.* -> anomaly:{} ---
    if "anomaly.type" in signal or "anomaly.score" in signal:
        signal.setdefault("anomaly", {})
        if "anomaly.type" in signal:
            signal["anomaly"]["type"] = signal.pop("anomaly.type")
        if "anomaly.score" in signal:
            signal["anomaly"]["score"] = signal.pop("anomaly.score")

    # --- Flattened k8s.replicas.current -> k8s:{replicas:{current}} ---
    if "k8s.replicas.current" in signal:
        signal.setdefault("k8s", {})
        signal["k8s"].setdefault("replicas", {})
        signal["k8s"]["replicas"]["current"] = signal.pop("k8s.replicas.current")

    # --- If nested anomaly exists but missing keys, leave as-is ---
    # --- If nested k8s exists but missing keys, leave as-is ---


def _merge_raw_preserve_detection(signal: dict, raw_patch: dict) -> None:
    """
    Merge raw fields without losing raw.detection.anomaly.
    """
    base_raw = signal.get("raw") or {}
    merged = {**base_raw, **(raw_patch or {})}
    merged.setdefault("detection", {})
    merged["detection"]["anomaly"] = True
    signal["raw"] = merged


# ============================================================
# Core evaluation logic
# ============================================================
def _evaluate_once(payload: dict | None = None) -> dict:
    policies = load_runtime_policies()

    # If caller provided a signal payload, evaluate ONLY that payload
    if payload and isinstance(payload.get("signal"), dict) and payload["signal"]:
        incoming_signal: Dict[str, Any] = payload["signal"] or {}

        # minimal canonical envelope so anomaly gating + target resolution work
        signal: Dict[str, Any] = {
            "service": payload.get("service") or incoming_signal.get("service"),
            "raw": {"incoming": payload, "detection": {"anomaly": True}},
        }

        # Merge all incoming keys but protect raw.detection.anomaly
        for k, v in incoming_signal.items():
            if k == "raw" and isinstance(v, dict):
                _merge_raw_preserve_detection(signal, v)
            else:
                signal[k] = v

        # External evaluate calls are considered "active anomaly" by definition
        _set_anomaly_active(signal)

        # Normalize flattened/nested representations for policy matching
        _normalize_signal(signal)

    else:
        # Default behavior (no payload given): use runtime adapter
        signal = load_runtime_signals()
        # Runtime adapter may already bring anomaly/k8s shapes; normalize anyway
        _normalize_signal(signal)

    anomaly_flag = bool((signal.get("raw") or {}).get("detection", {}).get("anomaly", False))

    if not anomaly_flag:
        decision = {"ts_utc": _utc_now(), "decision": "no_action", "reason": "no active anomaly"}
        _audit(decision)
        return decision

    chosen = evaluate_policies(policies, signal)

    if not chosen:
        decision = {"ts_utc": _utc_now(), "decision": "no_action", "reason": "no policy matched"}
        _audit(decision)
        return decision

    action_plan = _build_action_plan(chosen, signal)
    priority_result = calculate_priority(signal, action_plan)

    allowed, reason = apply_guardrails(action_plan)

    if priority_result["execution_mode"] == "OBSERVE_ONLY":
        allowed = False
        reason = "priority matrix selected observe-only mode"

    decision = {
        "ts_utc": _utc_now(),
        "decision": "action" if allowed else "blocked",
        "policy": chosen.name,
        "priority": chosen.priority,
        "priority_label": priority_result["priority_label"],
        "priority_score": priority_result["priority_score"],
        "execution_mode": priority_result["execution_mode"],
        "priority_explanation": priority_result["explanation"],
        "priority_factors": priority_result["factors"],
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
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")
    return _evaluate_once(payload)


@app.post("/v1/policies/validate")
def validate_policy(payload: dict = Body(default={})):
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return {
            "valid": False,
            "errors": [{"field": "body", "message": "Payload must be a JSON object"}],
            "warnings": [],
            "parsed": None,
            "safety": {
                "allowed_actions": False,
                "allowed_scope": False,
                "replica_bounds": False,
                "guardrails_present": False,
            },
        }

    return validate_policy_dsl(payload.get("dsl"), payload.get("mode", "draft"))


@app.get("/v1/policies")
def policies_list():
    return list_policy_definitions()


def _repository_error_response(exc: PolicyRepositoryError):
    content = {
        "status": "error",
        "message": exc.message,
    }
    if exc.validation is not None:
        content["validation"] = exc.validation
    return JSONResponse(status_code=exc.status_code, content=content)


def _require_policy_payload(payload: dict | None) -> dict:
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise PolicyRepositoryError(400, "Payload must be a JSON object.")
    return payload


def _request_actor_and_reason(data: dict, request: Request) -> tuple[str, str]:
    updated_by = str(data.get("updated_by") or request.query_params.get("updated_by") or "operator")
    reason = str(data.get("reason") or request.query_params.get("reason") or "")
    return updated_by, reason


@app.get("/v1/policies/change-audit")
def policies_change_audit(limit: int = 50):
    return list_change_audit(limit=limit)


@app.post("/v1/policies/reload")
def policies_reload(request: Request, payload: dict = Body(default={})):
    require_admin_key(request)
    try:
        data = _require_policy_payload(payload)
        updated_by, reason = _request_actor_and_reason(data, request)
        result = reload_policies(updated_by=updated_by, reason=reason)
        if result.get("status") != "ok":
            return JSONResponse(status_code=400, content=result)
        return result
    except PolicyRepositoryError as exc:
        return _repository_error_response(exc)


@app.get("/v1/policies/{policy_id}")
def policy_get(policy_id: str):
    policy = get_policy_definition(policy_id)
    if not policy:
        return JSONResponse(
            status_code=404,
            content={
                "status": "error",
                "message": "Policy not found",
            },
        )
    return {
        "status": "ok",
        "policy": policy,
    }


@app.post("/v1/policies")
def policy_create(request: Request, payload: dict = Body(default={})):
    require_admin_key(request)
    try:
        data = _require_policy_payload(payload)
        updated_by = str(data.get("updated_by") or "operator")
        policy = create_policy(data, updated_by=updated_by)
        return {
            "status": "ok",
            "operation": "create",
            "policy": policy,
        }
    except PolicyRepositoryError as exc:
        return _repository_error_response(exc)


@app.put("/v1/policies/{policy_id}")
def policy_update(policy_id: str, request: Request, payload: dict = Body(default={})):
    require_admin_key(request)
    try:
        data = _require_policy_payload(payload)
        updated_by = str(data.get("updated_by") or "operator")
        policy = update_policy(policy_id, data, updated_by=updated_by)
        return {
            "status": "ok",
            "operation": "update",
            "policy": policy,
        }
    except PolicyRepositoryError as exc:
        return _repository_error_response(exc)


@app.delete("/v1/policies/{policy_id}")
def policy_delete(policy_id: str, request: Request, payload: dict = Body(default={})):
    require_admin_key(request)
    try:
        data = _require_policy_payload(payload)
        updated_by = str(data.get("updated_by") or request.query_params.get("updated_by") or "operator")
        reason = data.get("reason") or request.query_params.get("reason") or ""
        policy = soft_delete_policy(policy_id, updated_by=updated_by, reason=reason)
        return {
            "status": "ok",
            "operation": "delete",
            "policy": policy,
        }
    except PolicyRepositoryError as exc:
        return _repository_error_response(exc)


@app.post("/v1/policies/{policy_id}/enable")
def policy_enable(policy_id: str, request: Request, payload: dict = Body(default={})):
    require_admin_key(request)
    try:
        data = _require_policy_payload(payload)
        updated_by, reason = _request_actor_and_reason(data, request)
        policy = enable_policy(policy_id, updated_by=updated_by, reason=reason)
        active_count = list_policy_definitions().get("policies", [])
        active_policy_count = len(
            [
                item
                for item in active_count
                if item.get("enabled") is True
                and item.get("deleted") is False
                and item.get("status") == "active"
            ]
        )
        return {
            "status": "ok",
            "operation": "enable",
            "policy": policy,
            "active_policy_count": active_policy_count,
        }
    except PolicyRepositoryError as exc:
        return _repository_error_response(exc)


@app.post("/v1/policies/{policy_id}/disable")
def policy_disable(policy_id: str, request: Request, payload: dict = Body(default={})):
    require_admin_key(request)
    try:
        data = _require_policy_payload(payload)
        updated_by, reason = _request_actor_and_reason(data, request)
        policy = disable_policy(policy_id, updated_by=updated_by, reason=reason)
        active_count = list_policy_definitions().get("policies", [])
        active_policy_count = len(
            [
                item
                for item in active_count
                if item.get("enabled") is True
                and item.get("deleted") is False
                and item.get("status") == "active"
            ]
        )
        return {
            "status": "ok",
            "operation": "disable",
            "policy": policy,
            "active_policy_count": active_policy_count,
        }
    except PolicyRepositoryError as exc:
        return _repository_error_response(exc)


@app.get("/v1/admin/verify")
def admin_verify(request: Request):
    require_admin_key(request)
    return {
        "status": "ok",
        "admin": True,
        "service": "policy-engine",
    }


@app.get("/v1/policy/audit/latest")
def audit_latest(n: int = 20):
    if n <= 0:
        return {"ok": True, "returned": 0, "events": []}

    if not AUDIT_PATH.exists():
        return {"ok": True, "returned": 0, "events": []}

    lines = AUDIT_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    tail = lines[-max(1, n) :]

    events = []
    for ln in tail:
        try:
            events.append(json.loads(ln))
        except Exception:
            continue

    return {"ok": True, "returned": len(events), "events": events}
