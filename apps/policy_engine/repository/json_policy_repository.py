from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.policy_engine.dsl.parser import parse_policies
from apps.policy_engine.repository.policy_store import DEFAULT_POLICY_PATH
from apps.policy_engine.runtime.policy_validator import validate_policy_dsl

POLICY_STORE_ENV = "POLICY_STORE_PATH"
DEFAULT_POLICY_STORE_PATH = "/policy_engine/store/policies.json"


class PolicyRepositoryError(Exception):
    def __init__(self, status_code: int, message: str, validation: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.validation = validation


def get_policy_store_path() -> Path:
    return Path(os.getenv(POLICY_STORE_ENV, DEFAULT_POLICY_STORE_PATH))


def get_policy_store_dir() -> Path:
    return get_policy_store_path().parent


def get_policy_backup_dir() -> Path:
    return get_policy_store_dir() / "policy_backups"


def get_policy_change_audit_path() -> Path:
    return get_policy_store_dir() / "policy_change_audit.jsonl"


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _slugify_policy_id(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip()).strip("_")
    return normalized or "policy"


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
        "description": policy.get("description"),
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


def _load_store_payload_for_write() -> dict[str, Any]:
    store_path = get_policy_store_path()

    if not store_path.exists():
        bootstrap = _load_bootstrap_policies()
        if bootstrap.get("status") != "ok":
            raise PolicyRepositoryError(
                500,
                bootstrap.get("message") or "Failed to initialize policy store from bootstrap policies.",
            )
        return {
            "schema_version": 1,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "source": "bootstrap-default-policy",
            "policies": bootstrap.get("policies", []),
        }

    try:
        payload = json.loads(store_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PolicyRepositoryError(500, f"Policy store could not be loaded safely: {exc}") from exc

    if not isinstance(payload, dict):
        raise PolicyRepositoryError(500, "Policy store JSON must be an object.")

    raw_policies = payload.get("policies")
    if not isinstance(raw_policies, list):
        raise PolicyRepositoryError(500, "Policy store JSON must contain a policies list.")

    payload["policies"] = [
        _normalize_store_policy(policy)
        for policy in raw_policies
        if isinstance(policy, dict) and (policy.get("id") or policy.get("name"))
    ]
    payload.setdefault("schema_version", 1)
    payload.setdefault("source", "policy-store")
    return payload


def write_store_atomic(data: dict[str, Any]) -> None:
    store_path = get_policy_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = store_path.with_name(f".{store_path.name}.tmp")

    encoded = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())

    os.replace(tmp_path, store_path)


def backup_store(reason: str) -> str | None:
    store_path = get_policy_store_path()
    if not store_path.exists():
        return None

    backup_dir = get_policy_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    safe_reason = _slugify_policy_id(reason or "change")[:60]
    backup_path = backup_dir / f"{datetime.utcnow().strftime('%Y%m%dT%H%M%S%fZ')}_{safe_reason}.json"
    backup_path.write_text(store_path.read_text(encoding="utf-8"), encoding="utf-8")
    return str(backup_path)


def append_change_audit(event: dict[str, Any]) -> None:
    audit_path = get_policy_change_audit_path()
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _policy_index(policies: list[dict[str, Any]], policy_id: str) -> int | None:
    for index, policy in enumerate(policies):
        if policy.get("id") == policy_id:
            return index
    return None


def _validation_to_single_policy(validation: dict[str, Any], requested_name: str) -> dict[str, Any]:
    if not validation.get("valid"):
        raise PolicyRepositoryError(400, "Policy DSL validation failed.", validation)

    parsed_policies = ((validation.get("parsed") or {}).get("policies") or [])
    if len(parsed_policies) != 1:
        raise PolicyRepositoryError(
            400,
            "Policy DSL must contain exactly one POLICY block for create/update.",
            validation,
        )

    parsed_policy = parsed_policies[0]
    parsed_name = parsed_policy.get("name")
    if parsed_name and parsed_name != requested_name:
        validation = {
            **validation,
            "errors": [
                *validation.get("errors", []),
                {
                    "field": "name",
                    "message": f"Request name '{requested_name}' must match DSL policy name '{parsed_name}'.",
                },
            ],
        }
        raise PolicyRepositoryError(400, "Policy name does not match DSL policy name.", validation)

    return parsed_policy


def _build_policy_record(
    *,
    policy_id: str,
    name: str,
    dsl: str,
    validation: dict[str, Any],
    parsed_policy: dict[str, Any],
    updated_by: str,
    description: str | None = None,
    created_at: str | None = None,
    version: int = 1,
) -> dict[str, Any]:
    now = _utc_now()
    return {
        "id": policy_id,
        "name": name,
        "description": description,
        "dsl": dsl,
        "enabled": False,
        "status": "draft",
        "version": version,
        "created_at": created_at or now,
        "updated_at": now,
        "updated_by": updated_by,
        "source": "operator",
        "deleted": False,
        "validation": validation,
        "parsed": {
            "priority": parsed_policy.get("priority"),
            "action": parsed_policy.get("action"),
            "conditions": parsed_policy.get("conditions", []),
        },
    }


def _audit_event(
    *,
    operation: str,
    policy: dict[str, Any] | None = None,
    updated_by: str,
    reason: str | None,
    valid: bool,
    success: bool | None = None,
    active_policy_count: int | None = None,
) -> dict[str, Any]:
    return {
        "ts_utc": _utc_now(),
        "operation": operation,
        "policy_id": (policy or {}).get("id"),
        "policy_name": (policy or {}).get("name"),
        "updated_by": updated_by,
        "version": (policy or {}).get("version"),
        "reason": reason or "",
        "active_policy_count": active_policy_count,
        "valid": valid,
        "success": valid if success is None else success,
    }


def create_policy(payload: dict[str, Any], updated_by: str) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    dsl = str(payload.get("dsl") or "").strip()
    if not name:
        raise PolicyRepositoryError(400, "Policy name is required.")
    if not dsl:
        raise PolicyRepositoryError(400, "Policy DSL is required.")

    policy_id = _slugify_policy_id(str(payload.get("id") or name))
    store = _load_store_payload_for_write()
    policies = store["policies"]

    existing_index = _policy_index(policies, policy_id)
    if existing_index is not None and not policies[existing_index].get("deleted"):
        raise PolicyRepositoryError(409, f"Policy id '{policy_id}' already exists.")

    validation = validate_policy_dsl(dsl, "draft")
    parsed_policy = _validation_to_single_policy(validation, name)
    policy = _build_policy_record(
        policy_id=policy_id,
        name=name,
        dsl=dsl,
        validation=validation,
        parsed_policy=parsed_policy,
        updated_by=updated_by,
        description=payload.get("description"),
    )

    if existing_index is None:
        policies.append(policy)
    else:
        policies[existing_index] = policy

    store["updated_at"] = _utc_now()
    store["source"] = "policy-store"
    write_store_atomic(store)
    append_change_audit(
        _audit_event(
            operation="create",
            policy=policy,
            updated_by=updated_by,
            reason=payload.get("reason"),
            valid=True,
        )
    )
    return policy


def update_policy(policy_id: str, payload: dict[str, Any], updated_by: str) -> dict[str, Any]:
    store = _load_store_payload_for_write()
    if not get_policy_store_path().exists():
        write_store_atomic(store)

    policies = store["policies"]
    index = _policy_index(policies, policy_id)
    if index is None or policies[index].get("deleted"):
        raise PolicyRepositoryError(404, "Policy not found.")

    current = policies[index]
    name = str(payload.get("name") or current.get("name") or "").strip()
    dsl = str(payload.get("dsl") or "").strip()
    if not name:
        raise PolicyRepositoryError(400, "Policy name is required.")
    if not dsl:
        raise PolicyRepositoryError(400, "Policy DSL is required.")

    validation = validate_policy_dsl(dsl, "draft")
    parsed_policy = _validation_to_single_policy(validation, name)
    backup_store(payload.get("reason") or f"update_{policy_id}")

    updated = _build_policy_record(
        policy_id=policy_id,
        name=name,
        dsl=dsl,
        validation=validation,
        parsed_policy=parsed_policy,
        updated_by=updated_by,
        description=payload.get("description", current.get("description")),
        created_at=current.get("created_at"),
        version=_safe_int(current.get("version"), 1) + 1,
    )

    policies[index] = updated
    store["updated_at"] = _utc_now()
    store["source"] = "policy-store"
    write_store_atomic(store)
    append_change_audit(
        _audit_event(
            operation="update",
            policy=updated,
            updated_by=updated_by,
            reason=payload.get("reason"),
            valid=True,
        )
    )
    return updated


def soft_delete_policy(policy_id: str, updated_by: str, reason: str | None = None) -> dict[str, Any]:
    store = _load_store_payload_for_write()
    if not get_policy_store_path().exists():
        write_store_atomic(store)

    policies = store["policies"]
    index = _policy_index(policies, policy_id)
    if index is None or policies[index].get("deleted"):
        raise PolicyRepositoryError(404, "Policy not found.")

    backup_store(reason or f"delete_{policy_id}")
    policy = {
        **policies[index],
        "enabled": False,
        "status": "deleted",
        "deleted": True,
        "updated_at": _utc_now(),
        "updated_by": updated_by,
        "version": _safe_int(policies[index].get("version"), 1) + 1,
    }

    policies[index] = policy
    store["updated_at"] = _utc_now()
    store["source"] = "policy-store"
    write_store_atomic(store)
    append_change_audit(
        _audit_event(
            operation="delete",
            policy=policy,
            updated_by=updated_by,
            reason=reason,
            valid=bool((policy.get("validation") or {}).get("valid")),
        )
    )
    return policy


def list_change_audit(limit: int = 50) -> dict[str, Any]:
    audit_path = get_policy_change_audit_path()
    if not audit_path.exists():
        return {
            "status": "ok",
            "source": "policy-change-audit",
            "audit_path": str(audit_path),
            "count": 0,
            "events": [],
        }

    lines = audit_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    tail = lines[-max(1, limit) :]
    events = []
    for line in tail:
        try:
            events.append(json.loads(line))
        except Exception:
            continue

    return {
        "status": "ok",
        "source": "policy-change-audit",
        "audit_path": str(audit_path),
        "count": len(events),
        "events": events,
    }


def get_active_policy_definitions() -> dict[str, Any]:
    payload = list_policy_definitions()
    policies = [
        policy
        for policy in payload.get("policies", [])
        if policy.get("enabled") is True
        and policy.get("deleted") is False
        and policy.get("status") == "active"
        and (policy.get("validation") or {}).get("valid") is True
        and bool(policy.get("dsl"))
    ]

    return {
        "status": payload.get("status", "ok"),
        "source": payload.get("source", "policy-store"),
        "store_path": payload.get("store_path", str(get_policy_store_path())),
        "active_policy_count": len(policies),
        "policies": policies,
        "warnings": payload.get("warnings", []),
    }


def _combined_dsl(policies: list[dict[str, Any]]) -> str:
    return "\n\n".join(str(policy.get("dsl") or "").strip() for policy in policies if policy.get("dsl"))


def validate_active_policy_set(candidate_policies: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if candidate_policies is None:
        active_payload = get_active_policy_definitions()
        source = active_payload.get("source", "policy-store")
        if source == "policy-store":
            candidate_policies = active_payload.get("policies", [])
        else:
            candidate_policies = []
    else:
        source = "policy-store"

    active_count = len(candidate_policies)
    if active_count == 0:
        bootstrap = _load_bootstrap_policies()
        candidate_policies = bootstrap.get("policies", [])
        source = "default-policy-fallback"

    dsl = _combined_dsl(candidate_policies)
    validation = validate_policy_dsl(dsl, "draft")
    return {
        "valid": bool(validation.get("valid")),
        "source": source,
        "active_policy_count": active_count,
        "validation": validation,
    }


def _replace_policy(policies: list[dict[str, Any]], updated_policy: dict[str, Any]) -> None:
    index = _policy_index(policies, str(updated_policy.get("id")))
    if index is None:
        policies.append(updated_policy)
    else:
        policies[index] = updated_policy


def enable_policy(policy_id: str, updated_by: str, reason: str | None = None) -> dict[str, Any]:
    store = _load_store_payload_for_write()
    if not get_policy_store_path().exists():
        write_store_atomic(store)

    policies = store["policies"]
    index = _policy_index(policies, policy_id)
    if index is None:
        raise PolicyRepositoryError(404, "Policy not found.")

    current = policies[index]
    if current.get("deleted"):
        raise PolicyRepositoryError(400, "Soft-deleted policies cannot be enabled.")
    if not current.get("dsl"):
        raise PolicyRepositoryError(400, "Policy DSL is required before enabling.")

    selected_validation = validate_policy_dsl(current.get("dsl"), "draft")
    if not selected_validation.get("valid"):
        raise PolicyRepositoryError(400, "Policy DSL validation failed.", selected_validation)

    candidate = {
        **current,
        "enabled": True,
        "status": "active",
        "deleted": False,
        "validation": selected_validation,
    }

    active_candidates = [
        policy
        for policy in policies
        if policy.get("id") != policy_id
        and policy.get("enabled") is True
        and policy.get("deleted") is False
        and policy.get("status") == "active"
        and (policy.get("validation") or {}).get("valid") is True
        and bool(policy.get("dsl"))
    ]
    active_candidates.append(candidate)
    active_validation = validate_active_policy_set(active_candidates)
    if not active_validation.get("valid"):
        raise PolicyRepositoryError(
            400,
            "Active policy set validation failed.",
            active_validation.get("validation"),
        )

    backup_store(reason or f"enable_{policy_id}")
    enabled_policy = {
        **candidate,
        "version": _safe_int(current.get("version"), 1) + 1,
        "updated_at": _utc_now(),
        "updated_by": updated_by,
    }
    _replace_policy(policies, enabled_policy)
    store["updated_at"] = _utc_now()
    store["source"] = "policy-store"
    write_store_atomic(store)
    append_change_audit(
        _audit_event(
            operation="enable",
            policy=enabled_policy,
            updated_by=updated_by,
            reason=reason,
            valid=True,
            success=True,
            active_policy_count=active_validation.get("active_policy_count"),
        )
    )
    return enabled_policy


def disable_policy(policy_id: str, updated_by: str, reason: str | None = None) -> dict[str, Any]:
    store = _load_store_payload_for_write()
    if not get_policy_store_path().exists():
        write_store_atomic(store)

    policies = store["policies"]
    index = _policy_index(policies, policy_id)
    if index is None:
        raise PolicyRepositoryError(404, "Policy not found.")

    current = policies[index]
    backup_store(reason or f"disable_{policy_id}")
    disabled_policy = {
        **current,
        "enabled": False,
        "status": "deleted" if current.get("deleted") else "disabled",
        "version": _safe_int(current.get("version"), 1) + 1,
        "updated_at": _utc_now(),
        "updated_by": updated_by,
    }
    _replace_policy(policies, disabled_policy)
    store["updated_at"] = _utc_now()
    store["source"] = "policy-store"
    write_store_atomic(store)

    active_count = get_active_policy_definitions().get("active_policy_count", 0)
    append_change_audit(
        _audit_event(
            operation="disable",
            policy=disabled_policy,
            updated_by=updated_by,
            reason=reason,
            valid=True,
            success=True,
            active_policy_count=active_count,
        )
    )
    return disabled_policy


def reload_policies(updated_by: str, reason: str | None = None) -> dict[str, Any]:
    active_validation = validate_active_policy_set()
    valid = bool(active_validation.get("valid"))
    operation = "reload" if valid else "reload_failed"
    append_change_audit(
        _audit_event(
            operation=operation,
            policy=None,
            updated_by=updated_by,
            reason=reason,
            valid=valid,
            success=valid,
            active_policy_count=active_validation.get("active_policy_count"),
        )
    )

    response = {
        "status": "ok" if valid else "error",
        "operation": "reload",
        "active_policy_count": active_validation.get("active_policy_count", 0),
        "source": active_validation.get("source"),
        "validation": active_validation.get("validation"),
    }
    if not valid:
        response["message"] = "Active policy set validation failed."
    return response


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
