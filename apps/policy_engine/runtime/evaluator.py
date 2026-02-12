from __future__ import annotations

from typing import Any
from apps.policy_engine.dsl.model import Policy, Condition


def _compare(lhs: Any, op: str, rhs: Any) -> bool:
    if op == "==":
        return lhs == rhs
    if op == ">":
        return float(lhs) > float(rhs)
    if op == "<":
        return float(lhs) < float(rhs)
    if op == ">=":
        return float(lhs) >= float(rhs)
    if op == "<=":
        return float(lhs) <= float(rhs)
    return False


def _get_field_value(signal: dict, field: str) -> Any:
    """
    Supports:
      1) flat keys: signal["anomaly.type"]
      2) nested dicts via dot-path: signal["anomaly"]["type"]
    """
    # Fast path: exact match (flat dict style)
    if field in signal:
        return signal.get(field)

    # Dot-path traversal for nested dict style
    cur: Any = signal
    for part in field.split("."):
        if not isinstance(cur, dict):
            return None
        if part not in cur:
            return None
        cur = cur.get(part)
    return cur


def _match_condition(cond: Condition, signal: dict) -> bool:
    lhs = _get_field_value(signal, cond.field)
    if lhs is None:
        return False
    return _compare(lhs, cond.op, cond.value)


def evaluate_policies(policies: list[Policy], signal: dict):
    matched: list[Policy] = []
    for p in policies:
        ok = all(_match_condition(c, signal) for c in p.conditions)
        if ok:
            matched.append(p)

    if not matched:
        return None

    # tie-break: highest priority first (MVP)
    matched.sort(key=lambda p: p.priority, reverse=True)
    return matched[0]
