from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from apps.policy_engine.dsl.parser import parse_policies
from apps.policy_engine.repository.policy_store import DEFAULT_POLICY_PATH

POLICY_STORE_ENV = "POLICY_STORE_PATH"
DEFAULT_POLICY_STORE_PATH = "/policy_engine/store/policies.json"


def get_policy_store_path() -> Path:
    return Path(os.getenv(POLICY_STORE_ENV, DEFAULT_POLICY_STORE_PATH))


def _condition_to_dict(condition: Any) -> dict[str, Any]:
    return {
        "field": condition.field,
        "op": condition.op,
        "value": condition.value,
    }


def _action_to_dict(action: Any) -> dict[str, Any]:
    data = {"type": action.type}
    if action.replicas is not None:
        data["replicas"] = action.replicas
    return data


def _policy_to_definition(policy: Any, dsl: str, source: str) -> dict[str, Any]:
    return {
        "id": policy.name,
        "name": policy.name,
        "dsl": dsl,
        "enabled": True,
        "status": "active",
        "version": 1,
        "created_at": None,
        "updated_at": None,
        "updated_by": "bootstrap" if source == "bootstrap-default-policy" else None,
        "source": source,
        "deleted": False,
        "validation": {
            "valid": True,
            "warnings": [],
        },
        "parsed": {
            "priority": policy.priority,
            "action": _action_to_dict(policy.action),
            "conditions": [_condition_to_dict(condition) for condition in policy.conditions],
        },
    }


def _safe_int(value: Any, fallback: int = 1) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _extract_policy_blocks(policy_text: str) -> dict[str, str]:
    matches = list(re.finditer(r'(?m)^POLICY\s+"([^"]+)"\s*:', policy_text))
    blocks: dict[str, str] = {}

    for index, match in enumerate(matches):
        name = match.group(1)
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(policy_text)
        blocks[name] = policy_text[start:end].strip()

    return blocks


def _load_bootstrap_policies(warnings: list[dict[str, str]] | None = None) -> dict[str, Any]:
    warnings = warnings or []
    store_path = get_policy_store_path()

    try:
        policy_text = DEFAULT_POLICY_PATH.read_text(encoding="utf-8")
        parsed_policies = parse_policies(policy_text)
    except Exception as exc:  # noqa: BLE001 - repository reads should fail gracefully
        return {
            "status": "error",
            "source": "bootstrap-default-policy",
            "store_path": str(store_path),
            "count": 0,
            "policies": [],
            "warnings": warnings,
            "message": f"Failed to parse bootstrap default policy: {exc}",
        }

    blocks = _extract_policy_blocks(policy_text)
    policies = []

    for policy in parsed_policies:
        block = blocks.get(policy.name)
        policy_warnings = list(warnings)
        if block is None:
            block = policy_text
            policy_warnings.append(
                {
                    "field": "dsl",
                    "message": "Exact policy block could not be extracted; full default policy text is shown.",
                }
            )

        definition = _policy_to_definition(policy, block, "bootstrap-default-policy")
        if policy_warnings:
            definition["validation"]["warnings"] = policy_warnings
        policies.append(definition)

    return {
        "status": "ok",
        "source": "bootstrap-default-policy",
        "store_path": str(store_path),
        "count": len(policies),
        "policies": policies,
        "warnings": warnings,
    }


def _normalize_store_policy(policy: dict[str, Any]) -> dict[str, Any]:
    policy_id = str(policy.get("id") or policy.get("name") or "")
    name = str(policy.get("name") or policy_id)

    normalized = {
        "id": policy_id,
        "name": name,
        "dsl": policy.get("dsl") or "",
        "enabled": bool(policy.get("enabled", True)),
        "status": policy.get("status") or ("active" if policy.get("enabled", True) else "disabled"),
        "version": _safe_int(policy.get("version") or 1),
        "created_at": policy.get("created_at"),
        "updated_at": policy.get("updated_at"),
        "updated_by": policy.get("updated_by"),
        "source": policy.get("source") or "policy-store",
        "deleted": bool(policy.get("deleted", False)),
        "validation": policy.get("validation") or {"valid": None, "warnings": []},
        "parsed": policy.get("parsed"),
    }

    return normalized


def _load_store_policies(store_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - fall back rather than crashing
        return _load_bootstrap_policies(
            warnings=[
                {
                    "field": "policy_store",
                    "message": f"Policy store could not be loaded; using bootstrap defaults. Error: {exc}",
                }
            ]
        )

    raw_policies = payload.get("policies") if isinstance(payload, dict) else payload
    if not isinstance(raw_policies, list):
        return _load_bootstrap_policies(
            warnings=[
                {
                    "field": "policy_store",
                    "message": "Policy store JSON did not contain a policies list; using bootstrap defaults.",
                }
            ]
        )

    policies = [
        _normalize_store_policy(policy)
        for policy in raw_policies
        if isinstance(policy, dict) and (policy.get("id") or policy.get("name"))
    ]

    return {
        "status": "ok",
        "source": "policy-store",
        "store_path": str(store_path),
        "count": len(policies),
        "policies": policies,
        "warnings": [],
    }


def list_policy_definitions() -> dict[str, Any]:
    store_path = get_policy_store_path()
    if store_path.exists():
        return _load_store_policies(store_path)
    return _load_bootstrap_policies()


def get_policy_definition(policy_id: str) -> dict[str, Any] | None:
    payload = list_policy_definitions()
    for policy in payload.get("policies", []):
        if policy.get("id") == policy_id or policy.get("name") == policy_id:
            return policy
    return None
