from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..models.action_models import ActionRequest


class PolicyDecisionType(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class PolicyDecision:
    decision: PolicyDecisionType
    reason: Optional[str] = None


class PolicyDecisionError(Exception):
    """
    Raised when the Policy Engine returns an invalid response or cannot be reached.
    This mirrors the orchestrator_service expectation.
    """
    pass


async def check_policy(action: ActionRequest) -> PolicyDecision:
    """
    Placeholder Policy Engine client.

    For now: always ALLOW.
    """
    return PolicyDecision(decision=PolicyDecisionType.ALLOW)
