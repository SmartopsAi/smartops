from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional

from apps.policy_engine.dsl.model import Policy


def evaluate_signal(
    service: str,
    anomaly: Dict[str, Any],
    rca: Dict[str, Any],
    policies: List[Policy],
) -> Tuple[Optional[str], Optional[Dict[str, Any]], bool, Optional[str]]:
    """
    Returns:
      (chosen_policy_name, action_dict, blocked_by_guardrails, reason)

    Why:
      - evaluate uses policy list passed from PolicyStore
      - supports reload (policies can change at runtime)
    """

    # ---- 1) match policies ----
    matched: List[Policy] = []
    for p in policies:
        if _policy_matches(p, anomaly=anomaly, rca=rca):
            matched.append(p)

    if not matched:
        return None, None, False, "No matching policy."

    # ---- 2) priority resolution ----
    # highest PRIORITY wins
    chosen = sorted(matched, key=lambda x: x.priority, reverse=True)[0]

    # ---- 3) convert action to dict (your existing structure may differ) ----
    action_dict = {
        "type": chosen.action.type,   # e.g. "restart" or "scale"
        "service": service,
        "replicas": getattr(chosen.action, "replicas", None),
    }

    # ---- 4) guardrails (placeholder) ----
    # Replace with your real guardrails logic
    blocked = False
    reason = f"Chosen by priority: {chosen.priority}"

    return chosen.name, action_dict, blocked, reason


def _policy_matches(policy: Policy, anomaly: Dict[str, Any], rca: Dict[str, Any]) -> bool:
    """
    Why: keep matching logic in one place.
    Replace with your real condition evaluation logic from STEP 6.
    """
    # This is a placeholder that assumes your Policy has conditions like:
    # policy.conditions: List[Condition(field, op, value)]
    for cond in policy.conditions:
        left = None
        if cond.field.startswith("anomaly."):
            left = anomaly.get(cond.field.split(".", 1)[1])
        elif cond.field.startswith("rca."):
            left = rca.get(cond.field.split(".", 1)[1])

        if not _compare(left, cond.op, cond.value):
            return False

    return True


def _compare(left: Any, op: str, right: Any) -> bool:
    if op == "==":
        return left == right
    if op == ">":
        return left is not None and left > right
    if op == "<":
        return left is not None and left < right
    if op == ">=":
        return left is not None and left >= right
    if op == "<=":
        return left is not None and left <= right
    return False
