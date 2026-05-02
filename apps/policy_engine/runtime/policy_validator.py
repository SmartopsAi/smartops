from __future__ import annotations

from typing import Any

from apps.policy_engine.dsl.parser import parse_policies

ALLOWED_ACTIONS = {"scale", "restart"}
ALLOWED_NAMESPACES = {"smartops-dev"}
ALLOWED_DEPLOYMENTS = {"smartops-erp-simulator", "odoo-web"}
ALLOWED_SERVICES = {"erp-simulator", "odoo", *ALLOWED_DEPLOYMENTS}
MIN_REPLICAS = 1
MAX_REPLICAS = 6


def _base_safety(value: bool = False) -> dict[str, bool]:
    return {
        "allowed_actions": value,
        "allowed_scope": value,
        "replica_bounds": value,
        "guardrails_present": value,
    }


def _error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}


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


def _action_scope_is_allowed(action: Any) -> bool:
    namespace = getattr(action, "namespace", None)
    deployment = getattr(action, "deployment", None) or getattr(action, "target", None)

    if namespace is not None and namespace not in ALLOWED_NAMESPACES:
        return False
    if deployment is not None and deployment not in ALLOWED_DEPLOYMENTS:
        return False

    return True


def _condition_scope_errors(policy_index: int, conditions: list[Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    for condition_index, condition in enumerate(conditions):
        field = str(condition.field)
        value = condition.value
        if not isinstance(value, str) or condition.op != "==":
            continue

        error_field = f"policies[{policy_index}].conditions[{condition_index}]"
        if field == "namespace" and value not in ALLOWED_NAMESPACES:
            errors.append(_error(error_field, f"Namespace '{value}' is outside the allowed scope."))
        if field in {"service", "deployment", "target.deployment"} and value not in ALLOWED_SERVICES:
            errors.append(_error(error_field, f"Deployment/service '{value}' is outside the allowed scope."))

    return errors


def validate_policy_dsl(dsl: Any, mode: str = "draft") -> dict[str, Any]:
    """
    Validate draft DSL without writing, auditing, reloading, or evaluating runtime policies.
    """
    warnings: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    if not isinstance(dsl, str) or not dsl.strip():
        return {
            "valid": False,
            "errors": [_error("dsl", "DSL text is required.")],
            "warnings": warnings,
            "parsed": None,
            "safety": _base_safety(False),
        }

    if mode and mode != "draft":
        warnings.append(
            _error("mode", "Only draft validation is supported; no policy will be saved or deployed.")
        )

    try:
        policies = parse_policies(dsl)
    except Exception as exc:  # noqa: BLE001 - parser errors should become validation output
        return {
            "valid": False,
            "errors": [_error("dsl", f"DSL parse failed: {exc}")],
            "warnings": warnings,
            "parsed": None,
            "safety": _base_safety(False),
        }

    if not policies:
        return {
            "valid": False,
            "errors": [_error("dsl", "No policies were parsed from the supplied DSL.")],
            "warnings": warnings,
            "parsed": None,
            "safety": _base_safety(False),
        }

    allowed_actions = True
    allowed_scope = True
    replica_bounds = True
    guardrails_present = True
    parsed_policies: list[dict[str, Any]] = []

    for index, policy in enumerate(policies):
        field_prefix = f"policies[{index}]"
        action = policy.action

        scope_errors = _condition_scope_errors(index, policy.conditions)
        if scope_errors:
            allowed_scope = False
            errors.extend(scope_errors)

        if action.type not in ALLOWED_ACTIONS:
            allowed_actions = False
            errors.append(_error(f"{field_prefix}.action.type", f"Unsupported action '{action.type}'."))

        if not _action_scope_is_allowed(action):
            allowed_scope = False
            errors.append(
                _error(
                    f"{field_prefix}.action.target",
                    "Action target is outside the allowed smartops-dev deployment scope.",
                )
            )

        if action.type == "scale":
            if action.replicas is None:
                replica_bounds = False
                errors.append(_error(f"{field_prefix}.action.replicas", "Scale replicas are required."))
            elif action.replicas < MIN_REPLICAS or action.replicas > MAX_REPLICAS:
                replica_bounds = False
                errors.append(
                    _error(
                        f"{field_prefix}.action.replicas",
                        f"Scale replicas must be between {MIN_REPLICAS} and {MAX_REPLICAS}.",
                    )
                )

        if action.type in ALLOWED_ACTIONS:
            warnings.append(
                _error(
                    f"{field_prefix}.action.verify",
                    "Current DSL does not express verify=true/false; runtime action plans currently set verify=true.",
                )
            )

        guardrails: list[str] = []
        if action.type == "scale":
            guardrails.append(f"replica bounds {MIN_REPLICAS}-{MAX_REPLICAS}")
        if action.type == "restart":
            guardrails.append("runtime restart cooldown guardrail")

        if not guardrails:
            guardrails_present = False

        parsed_policies.append(
            {
                "name": policy.name,
                "conditions": [_condition_to_dict(condition) for condition in policy.conditions],
                "action": _action_to_dict(action),
                "priority": policy.priority,
                "guardrails": guardrails,
            }
        )

    safety = {
        "allowed_actions": allowed_actions,
        "allowed_scope": allowed_scope,
        "replica_bounds": replica_bounds,
        "guardrails_present": guardrails_present,
    }

    return {
        "valid": not errors and all(safety.values()),
        "errors": errors,
        "warnings": warnings,
        "parsed": {
            "policy_count": len(parsed_policies),
            "policies": parsed_policies,
        },
        "safety": safety,
    }
