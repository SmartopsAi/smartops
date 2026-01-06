from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any, Dict

import httpx

from ..models.action_models import ActionRequest


class PolicyDecisionType(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class PolicyDecision:
    decision: PolicyDecisionType
    reason: Optional[str] = None
    # Optional action plan from policy engine (JSON dict)
    action_plan: Optional[Dict[str, Any]] = None
    # Raw policy engine response for debugging
    raw: Optional[Dict[str, Any]] = None


class PolicyDecisionError(Exception):
    """
    Raised when the Policy Engine returns an invalid response or cannot be reached.
    """
    pass


def _policy_engine_base_url() -> str:
    """
    Policy Engine URL.

    Local dev default:
      http://127.0.0.1:5051

    In Kubernetes you can set:
      POLICY_ENGINE_URL=http://smartops-policy-engine:5051
    """
    return os.getenv("POLICY_ENGINE_URL", "http://127.0.0.1:5051").rstrip("/")


async def check_policy(action: ActionRequest) -> PolicyDecision:
    """
    Ask Policy Engine (DSL) whether remediation should happen.

    NOTE:
    - Current Policy Engine evaluates based on runtime files (latest_detection.json, latest_rca.json, etc.)
    - So we call it with no body (but POST is fine).
    """
    url = f"{_policy_engine_base_url()}/v1/policy/evaluate"

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(url)
    except Exception as exc:  # network, timeout, DNS, etc.
        raise PolicyDecisionError(f"Policy Engine unreachable: {exc}") from exc

    # If policy engine crashed or returned HTML, this protects you
    content_type = (resp.headers.get("content-type") or "").lower()
    if resp.status_code >= 400:
        raise PolicyDecisionError(f"Policy Engine HTTP {resp.status_code}: {resp.text[:200]}")
    if "application/json" not in content_type:
        raise PolicyDecisionError(f"Policy Engine returned non-JSON: {resp.text[:200]}")

    try:
        data = resp.json()
    except Exception as exc:
        raise PolicyDecisionError(f"Invalid JSON from Policy Engine: {exc}") from exc

    pe_decision = (data.get("decision") or "").lower()
    reason = data.get("reason") or data.get("guardrail_reason") or None
    action_plan = data.get("action_plan")

    # Map Policy Engine decision → orchestrator decision
    if pe_decision == "action" and action_plan:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason=reason,
            action_plan=action_plan,
            raw=data,
        )

    # "blocked" or "no_action" or missing action_plan → deny execution
    if pe_decision in {"blocked", "no_action"}:
        return PolicyDecision(
            decision=PolicyDecisionType.DENY,
            reason=reason or pe_decision,
            action_plan=None,
            raw=data,
        )

    # Unknown response shape
    raise PolicyDecisionError(f"Unexpected Policy Engine response: {data}")
