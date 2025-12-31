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

def _match_condition(cond: Condition, signal: dict) -> bool:
    lhs = signal.get(cond.field)
    if lhs is None:
        return False
    return _compare(lhs, cond.op, cond.value)

def evaluate_policies(policies: list[Policy], signal: dict):
    matched = []
    for p in policies:
        ok = all(_match_condition(c, signal) for c in p.conditions)
        if ok:
            matched.append(p)

    if not matched:
        return None

    # tie-break: highest priority first (MVP)
    matched.sort(key=lambda p: p.priority, reverse=True)
    return matched[0]
