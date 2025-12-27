from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from apps.policy_engine.dsl.model import Action, Policy
from apps.policy_engine.schemas.models import (
    ActionPlan,
    AnomalySignal,
    RcaSignal,
    ScaleSpec,
    Target,
)

# ----------------------
# Guardrail configuration
# ----------------------
MIN_REPLICAS = 1
MAX_REPLICAS = 10
RESTART_COOLDOWN_SECONDS = 120

# Track last restart time per target (namespace/name)
_last_restart_at: Dict[str, datetime] = {}


def _get_field_value_from_signal(field: str, signal: Union[AnomalySignal, RcaSignal]):
    """
    WHY:
    - Bridges DSL field names to real signal values.
    """
    if field == "anomaly.type":
        return signal.type if isinstance(signal, AnomalySignal) else None

    if field == "anomaly.score":
        return signal.score if isinstance(signal, AnomalySignal) else None

    if field == "rca.cause":
        if isinstance(signal, RcaSignal) and signal.rankedCauses:
            return signal.rankedCauses[0].cause
        return None

    if field == "rca.probability":
        if isinstance(signal, RcaSignal) and signal.rankedCauses:
            return signal.rankedCauses[0].probability
        return None

    return None


def _compare(op: str, left, right) -> bool:
    """
    WHY:
    - Safely evaluates DSL comparisons.
    """
    if left is None:
        return False

    if op == "==":
        return left == right
    if op == ">":
        return left > right
    if op == "<":
        return left < right
    if op == ">=":
        return left >= right
    if op == "<=":
        return left <= right

    return False


def _policy_matches(policy: Policy, signal: Union[AnomalySignal, RcaSignal]) -> bool:
    """
    WHY:
    - A policy matches only when ALL conditions are true (AND logic).
    """
    for cond in policy.conditions:
        left = _get_field_value_from_signal(cond.field, signal)
        if not _compare(cond.op, left, cond.value):
            return False
    return True


def _select_best_policy(matches: List[Policy]) -> Optional[Policy]:
    """
    WHY:
    - Conflict resolution:
      1) Highest priority wins
      2) If tie: more conditions wins (more specific)
    """
    if not matches:
        return None

    return sorted(matches, key=lambda p: (p.priority, len(p.conditions)), reverse=True)[0]


def _signal_summary(signal: Union[AnomalySignal, RcaSignal]) -> Dict[str, Any]:
    """
    WHY:
    - Keep audit logs readable (don’t dump full raw object).
    """
    if isinstance(signal, AnomalySignal):
        return {
            "signal_type": "anomaly",
            "service": signal.service,
            "windowId": signal.windowId,
            "anomaly_type": signal.type,
            "anomaly_score": signal.score,
        }

    top = signal.rankedCauses[0] if signal.rankedCauses else None
    return {
        "signal_type": "rca",
        "service": signal.service,
        "windowId": signal.windowId,
        "top_cause": top.cause if top else None,
        "top_probability": top.probability if top else None,
    }


def evaluate_signal_with_policies(
    signal: Union[AnomalySignal, RcaSignal],
    policies: List[Policy],
    policy_file_path: str,
    request_id: str,
) -> Tuple[ActionPlan, Dict[str, Any]]:
    """
    WHY (STEP 8):
    - Returns (ActionPlan, audit_event)
    - Audit event records:
      * signal summary
      * matched policies
      * chosen policy
      * final decision
      * guardrail reason
    """

    # Target is what orchestrator will act on
    target = Target(namespace="smartops-dev", name="erp-simulator", kind="Deployment")
    target_key = f"{target.namespace}/{target.name}"

    # 1) Match policies
    matches: List[Policy] = [p for p in policies if _policy_matches(p, signal)]
    best = _select_best_policy(matches)

    matched_policies = [
        {"name": p.name, "priority": p.priority, "conditions": len(p.conditions)}
        for p in matches
    ]

    # 2) If nothing matched -> safe fallback
    if best is None:
        plan = ActionPlan(type="restart", dry_run=True, verify=True, target=target)

        audit_event = {
            "ts_utc": datetime.utcnow().isoformat() + "Z",
            "request_id": request_id,
            "policy_file_path": policy_file_path,
            "policy_count_loaded": len(policies),
            "signal": _signal_summary(signal),
            "matched_policy_count": len(matches),
            "matched_policies": matched_policies,
            "chosen_policy": None,
            "decision": {"type": plan.type, "dry_run": plan.dry_run, "verify": plan.verify},
            "guardrails": {"applied": True, "reason": "no_match_fallback_restart_dry_run"},
        }
        return plan, audit_event

    chosen_policy_name = best.name
    chosen_priority = best.priority
    action: Action = best.action

    # 3) Apply guardrails + produce ActionPlan
    guardrail_reason = None

    # RESTART guardrail (cooldown)
    if action.kind == "restart":
        now = datetime.utcnow()
        last = _last_restart_at.get(target_key)

        if last and (now - last).total_seconds() < RESTART_COOLDOWN_SECONDS:
            plan = ActionPlan(type="restart", dry_run=True, verify=True, target=target)
            guardrail_reason = "restart_blocked_by_cooldown"
        else:
            _last_restart_at[target_key] = now
            plan = ActionPlan(type="restart", dry_run=False, verify=True, target=target)
            guardrail_reason = "restart_allowed"

        audit_event = {
            "ts_utc": datetime.utcnow().isoformat() + "Z",
            "request_id": request_id,
            "policy_file_path": policy_file_path,
            "policy_count_loaded": len(policies),
            "signal": _signal_summary(signal),
            "matched_policy_count": len(matches),
            "matched_policies": matched_policies,
            "chosen_policy": {"name": chosen_policy_name, "priority": chosen_priority},
            "decision": {"type": plan.type, "dry_run": plan.dry_run, "verify": plan.verify},
            "guardrails": {"applied": True, "reason": guardrail_reason},
        }
        return plan, audit_event

    # SCALE guardrail (min/max clamp)
    if action.kind == "scale":
        requested = action.scale_replicas or 1
        safe_replicas = max(MIN_REPLICAS, min(MAX_REPLICAS, requested))

        dry_run = False
        if requested < MIN_REPLICAS or requested > MAX_REPLICAS:
            dry_run = True
            guardrail_reason = "scale_outside_limits_clamped_dry_run"
        else:
            guardrail_reason = "scale_within_limits"

        plan = ActionPlan(
            type="scale",
            dry_run=dry_run,
            verify=True,
            target=target,
            scale=ScaleSpec(replicas=safe_replicas),
        )

        audit_event = {
            "ts_utc": datetime.utcnow().isoformat() + "Z",
            "request_id": request_id,
            "policy_file_path": policy_file_path,
            "policy_count_loaded": len(policies),
            "signal": _signal_summary(signal),
            "matched_policy_count": len(matches),
            "matched_policies": matched_policies,
            "chosen_policy": {"name": chosen_policy_name, "priority": chosen_priority},
            "decision": {
                "type": plan.type,
                "dry_run": plan.dry_run,
                "verify": plan.verify,
                "requested_replicas": requested,
                "replicas": safe_replicas,
            },
            "guardrails": {"applied": True, "reason": guardrail_reason},
        }
        return plan, audit_event

    # Unknown action fallback
    plan = ActionPlan(type="restart", dry_run=True, verify=True, target=target)
    audit_event = {
        "ts_utc": datetime.utcnow().isoformat() + "Z",
        "request_id": request_id,
        "policy_file_path": policy_file_path,
        "policy_count_loaded": len(policies),
        "signal": _signal_summary(signal),
        "matched_policy_count": len(matches),
        "matched_policies": matched_policies,
        "chosen_policy": {"name": chosen_policy_name, "priority": chosen_priority},
        "decision": {"type": plan.type, "dry_run": plan.dry_run, "verify": plan.verify},
        "guardrails": {"applied": True, "reason": "unknown_action_fallback_restart_dry_run"},
    }
    return plan, audit_event


def get_policy_status(policies: List[Policy], policy_file_path: str) -> dict:
    """
    WHY:
    - Used by /v1/policy/status endpoint.
    - Reports in-memory status.
    """
    return {
        "policy_file_path": policy_file_path,
        "policy_count": len(policies),
        "min_replicas": MIN_REPLICAS,
        "max_replicas": MAX_REPLICAS,
        "restart_cooldown_seconds": RESTART_COOLDOWN_SECONDS,
    }
