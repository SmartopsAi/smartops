from __future__ import annotations

import logging

from apps.policy_engine.dsl.parser import parse_policies
from apps.policy_engine.repository.json_policy_repository import (
    get_active_policy_definitions,
    get_policy_store_path,
    validate_active_policy_set,
)
from apps.policy_engine.repository.policy_store import load_default_policies

logger = logging.getLogger("smartops.policy_loader")


def _fallback_default_policies(reason: str):
    logger.warning("Using default.policy fallback for runtime policies: %s", reason)
    return load_default_policies()


def load_runtime_policies():
    """
    Load active policies from the PVC-backed policy store.

    Safety behavior:
    - Missing/malformed/empty/invalid store falls back to default.policy.
    - Draft, disabled, and deleted policies never participate.
    - Store errors never crash policy evaluation.
    """
    try:
        if not get_policy_store_path().exists():
            return _fallback_default_policies("policy store does not exist")

        active_payload = get_active_policy_definitions()
        if active_payload.get("source") != "policy-store":
            return _fallback_default_policies("policy store was unavailable or invalid")

        active_policies = active_payload.get("policies", [])

        if not active_policies:
            return _fallback_default_policies("no active enabled policies in policy store")

        active_validation = validate_active_policy_set(active_policies)
        if not active_validation.get("valid"):
            return _fallback_default_policies("active policy set failed validation")

        dsl = "\n\n".join(str(policy.get("dsl") or "").strip() for policy in active_policies)
        if not dsl.strip():
            return _fallback_default_policies("active policy DSL was empty")

        return parse_policies(dsl)
    except Exception as exc:  # noqa: BLE001 - runtime policy load must never break evaluation
        return _fallback_default_policies(f"policy store load failed: {exc}")
