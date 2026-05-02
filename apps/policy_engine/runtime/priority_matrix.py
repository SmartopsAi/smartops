from __future__ import annotations

from typing import Any, Dict


SERVICE_CRITICALITY = {
    "erp-simulator": 3,
    "odoo": 3,
    "postgres": 3,
    "database": 3,
    "api-gateway": 2,
    "worker": 2,
    "unknown": 1,
}

ACTION_RISK = {
    "restart": 2,
    "scale": 1,
    "rollback": 3,
    "patch": 3,
    "observe": 0,
}


def _get_nested(data: dict, path: str, default=None):
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur.get(part)
    return cur


def calculate_priority(signal: Dict[str, Any], action_plan: Dict[str, Any]) -> Dict[str, Any]:
    """
    Priority Matrix for SmartOps remediation decisions.

    Factors:
    - Anomaly severity based on anomaly score
    - RCA confidence / probability
    - Business/service criticality
    - Risk of selected remediation action

    Output:
    - P1: critical, auto execute
    - P2: high, auto execute with guardrails
    - P3: medium, dry-run or approval preferred
    - P4: low, observe only
    """
    anomaly_type = _get_nested(signal, "anomaly.type", "unknown")
    anomaly_score = float(_get_nested(signal, "anomaly.score", 0.0) or 0.0)
    rca_probability = float(_get_nested(signal, "rca.probability", 0.0) or 0.0)

    service = signal.get("service", "unknown")
    action_type = action_plan.get("type", "observe")

    service_score = SERVICE_CRITICALITY.get(service, SERVICE_CRITICALITY["unknown"])
    action_risk = ACTION_RISK.get(action_type, 1)

    if anomaly_score >= 0.9:
        severity_score = 3
        severity = "CRITICAL"
    elif anomaly_score >= 0.7:
        severity_score = 2
        severity = "WARNING"
    elif anomaly_score >= 0.4:
        severity_score = 1
        severity = "LOW"
    else:
        severity_score = 0
        severity = "NORMAL"

    if rca_probability >= 0.8:
        confidence_score = 3
    elif rca_probability >= 0.6:
        confidence_score = 2
    elif rca_probability > 0:
        confidence_score = 1
    else:
        confidence_score = 1

    total = (
        severity_score * 25
        + confidence_score * 15
        + service_score * 10
        + action_risk * 5
    )

    if total >= 110:
        label = "P1"
        mode = "AUTO_EXECUTE"
        explanation = "Critical service impact with high confidence."
    elif total >= 85:
        label = "P2"
        mode = "AUTO_EXECUTE_WITH_GUARDRAILS"
        explanation = "High-priority remediation with guardrail enforcement."
    elif total >= 60:
        label = "P3"
        mode = "DRY_RUN_OR_APPROVAL"
        explanation = "Medium priority; safer to verify before executing."
    else:
        label = "P4"
        mode = "OBSERVE_ONLY"
        explanation = "Low confidence or low operational impact."

    return {
        "priority_label": label,
        "priority_score": total,
        "execution_mode": mode,
        "explanation": explanation,
        "factors": {
            "anomaly_type": anomaly_type,
            "severity": severity,
            "anomaly_score": anomaly_score,
            "rca_probability": rca_probability,
            "service": service,
            "service_criticality": service_score,
            "action_type": action_type,
            "action_risk": action_risk,
        },
    }
