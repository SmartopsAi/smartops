from typing import List, Union, Dict

from datetime import datetime
from apps.policy_engine.dsl.model import Policy, Condition, Action
from apps.policy_engine.dsl.parser import load_policies_from_file
from apps.policy_engine.schemas.models import (
    AnomalySignal,
    RcaSignal,
    ActionPlan,
    Target,
    ScaleSpec,
)

# Path to your default policy file (relative to project root)
POLICY_FILE_PATH = "apps/policy_engine/repository/default.policy"

# ----------------------
# Guardrail configuration
# ----------------------
MIN_REPLICAS = 1
MAX_REPLICAS = 10
MAX_SCALE_STEP = 2  # (for future use if you compare against current replicas)

RESTART_COOLDOWN_SECONDS = 120

# Track last restart time per target (namespace/name)
_last_restart_at: Dict[str, datetime] = {}




# Load policies at startup, but don't crash the app if something goes wrong
# try:
#     POLICIES: List[Policy] = load_policies_from_file(POLICY_FILE_PATH)
#     print(f"Loaded {len(POLICIES)} policies from {POLICY_FILE_PATH}")
# except Exception as e:
#     print(f"⚠️ Failed to load policies from {POLICY_FILE_PATH}: {e}")
#     POLICIES: List[Policy] = []

def _load_policies_safe() -> List[Policy]:
    """
    Always load policies fresh from disk.
    This makes it easy to edit default.policy and see effects immediately.
    """
    try:
        policies = load_policies_from_file(POLICY_FILE_PATH)
        # Optional: small debug print
        # print(f"[PolicyEngine] Loaded {len(policies)} policies from {POLICY_FILE_PATH}")
        return policies
    except Exception as e:
        print(f"⚠️ Failed to load policies from {POLICY_FILE_PATH}: {e}")
        return []



def _get_field_value_from_signal(
    field: str, signal: Union[AnomalySignal, RcaSignal]
):
    """
    Map DSL field names to actual values from the signal object.

    Supported fields:
      - anomaly.type
      - anomaly.score
      - rca.cause
      - rca.probability
    """
    if field == "anomaly.type":
        if isinstance(signal, AnomalySignal):
            return signal.type
        return None

    if field == "anomaly.score":
        if isinstance(signal, AnomalySignal):
            return signal.score
        return None

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
    Compare left <op> right, where op is ==, >, <, >=, <=
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
    Returns True if all conditions in this policy are satisfied for the signal.
    """
    for cond in policy.conditions:
        left = _get_field_value_from_signal(cond.field, signal)
        if not _compare(cond.op, left, cond.value):
            return False
    return True


def evaluate_signal_with_policies(
    signal: Union[AnomalySignal, RcaSignal]
) -> ActionPlan:
    """
    Evaluate the incoming signal against loaded policies and
    produce an ActionPlan for the Orchestrator.

    - Load policies fresh from disk (so edits take effect immediately)
    - Find the first policy whose conditions all match
    - Apply guardrails BEFORE returning the ActionPlan
    """

    policies = _load_policies_safe()

    # For now, always act on the ERP simulator deployment
    target = Target(
        namespace="smartops-dev",
        name="erp-simulator",
        kind="Deployment",
    )
    target_key = f"{target.namespace}/{target.name}"

    for policy in policies:
        if _policy_matches(policy, signal):
            action: Action = policy.action

            # -----------------------
            # RESTART with cooldown
            # -----------------------
            if action.kind == "restart":
                now = datetime.utcnow()
                last = _last_restart_at.get(target_key)

                if last and (now - last).total_seconds() < RESTART_COOLDOWN_SECONDS:
                    return ActionPlan(
                        type="restart",
                        dry_run=True,
                        verify=True,
                        target=target,
                    )

                _last_restart_at[target_key] = now
                return ActionPlan(
                    type="restart",
                    dry_run=False,
                    verify=True,
                    target=target,
                )

            # -----------------------
            # SCALE with replica limits
            # -----------------------
            if action.kind == "scale":
                requested = action.scale_replicas or 1

                # Clamp to safe range
                safe_replicas = max(MIN_REPLICAS, min(MAX_REPLICAS, requested))

                dry_run = False
                if requested < MIN_REPLICAS or requested > MAX_REPLICAS:
                    dry_run = True

                return ActionPlan(
                    type="scale",
                    dry_run=dry_run,
                    verify=True,
                    target=target,
                    scale=ScaleSpec(replicas=safe_replicas),
                )

    # -----------------------
    # No policy matched or none loaded -> safe fallback
    # -----------------------
    return ActionPlan(
        type="restart",
        dry_run=True,
        verify=True,
        target=target,
    )
