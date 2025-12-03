
"""
Pydantic models for Orchestrator actions and K8s operations.

These models are used across:
  - /v1/actions/execute
  - /v1/k8s/scale
  - /v1/k8s/restart
  - Policy Engine → Orchestrator communication
  - Closed-loop feedback controllers
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field
from .verification_models import DeploymentVerificationResult


# ---------------------------------------------------------------------------
# Action Types
# ---------------------------------------------------------------------------

class ActionType(str, Enum):
    SCALE = "scale"
    RESTART = "restart"
    PATCH = "patch"


# ---------------------------------------------------------------------------
# Target: a Kubernetes resource
# ---------------------------------------------------------------------------

class K8sTarget(BaseModel):
    kind: str = Field(
        ...,
        description="Kubernetes resource kind, e.g., Deployment, StatefulSet",
    )
    namespace: str = Field(
        ...,
        description="Namespace of the target resource",
    )
    name: str = Field(
        ...,
        description="Name of the target resource",
    )


# ---------------------------------------------------------------------------
# Parameter models for SCALE & PATCH
# ---------------------------------------------------------------------------

class ScaleParams(BaseModel):
    replicas: int = Field(..., ge=0, description="Desired replica count")


class PatchParams(BaseModel):
    patch: Dict[str, Any] = Field(
        ...,
        description="Arbitrary JSON patch/merge patch body",
    )


# ---------------------------------------------------------------------------
# RunnerResult: structured output from ActionRunner
# ---------------------------------------------------------------------------

class RunnerResult(BaseModel):
    """
    Structured result returned by ActionRunner.

    Contains:
      - status: success | failed | dry_run
      - attempts: number of attempts made
      - duration_seconds: execution time
      - result: raw result from k8s_core (or None)
      - error: string message if failed
    """
    status: str = Field(..., description="success | failed | dry_run")
    attempts: int = Field(..., ge=0)
    duration_seconds: float = Field(..., ge=0)
    result: Optional[Any] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# High-level Action Request
# ---------------------------------------------------------------------------

class ActionRequest(BaseModel):
    """
    Generic action request that policy-engine or AI agents can send.
    """

    type: ActionType = Field(..., description="Type of action to perform")
    target: K8sTarget = Field(..., description="Target Kubernetes resource")

    # Options controlling orchestration behavior
    dry_run: bool = Field(
        False,
        description=(
            "If true, orchestrator performs a Kubernetes server-side dry run "
            "(or internal dry-run simulation where server-side is unavailable)."
        ),
    )
    reason: Optional[str] = Field(
        None,
        description="Human-readable reason or context for audit logs",
    )

    # Action-type specific parameters
    scale: Optional[ScaleParams] = None
    patch: Optional[PatchParams] = None

    # Verification controls
    verify: bool = Field(
        True,
        description="If true, orchestrator will verify rollout after executing the action.",
    )
    verify_timeout_seconds: int = Field(
        60,
        ge=5,
        le=600,
        description="Maximum time to wait for rollout verification.",
    )
    verify_poll_interval_seconds: int = Field(
        5,
        ge=1,
        le=60,
        description="Polling interval (in seconds) for rollout verification.",
    )


# ---------------------------------------------------------------------------
# High-level Action Result
# ---------------------------------------------------------------------------

class ActionResult(BaseModel):
    """
    High-level response for orchestrator actions.

    Returns:
      - success: boolean summary
      - message: human-readable
      - dry_run: was this a dry-run?
      - runner: ActionRunner structured output
      - verification: rollout verification summary (optional)
      - warnings: optional warnings (e.g., missing replicas, degraded status)
    """

    success: bool
    message: str
    dry_run: bool

    # Unified ActionRunner output
    details: Optional[Dict[str, Any]] = None

    # Optional rollout verification summary
    verification: Optional[DeploymentVerificationResult] = None

    # Optional warnings
    warnings: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Low-level Scale/Restart Requests for /v1/k8s/*
# ---------------------------------------------------------------------------

class ScaleRequest(BaseModel):
    namespace: str
    deployment: str
    replicas: int = Field(..., ge=0)
    dry_run: bool = False


class RestartRequest(BaseModel):
    namespace: str
    deployment: str
    dry_run: bool = False
