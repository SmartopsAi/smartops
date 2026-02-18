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
    Prefer nested dict (runtime) values over flat keys (incoming payload),
    so runtime-driven closed-loop cannot be overridden by trigger payload.
    Supports:
      - nested via dot-path: signal["anomaly"]["type"]
      - flat keys: signal["anomaly.type"]
    """

    # 1) Dot-path traversal FIRST (nested runtime wins)
    cur: Any = signal
    ok = True
    for part in field.split("."):
        if not isinstance(cur, dict) or part not in cur:
            ok = False
            break
        cur = cur.get(part)
    if ok:
        return cur

    # 2) Fallback: flat dict style (payload-driven)
    if field in signal:
        return signal.get(field)

    return None


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
