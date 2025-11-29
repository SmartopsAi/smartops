from enum import Enum
from typing import Optional, Dict, Any

from pydantic import BaseModel, Field


class VerificationStatus(str, Enum):
    """High-level verification state for a remediation action."""
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class DeploymentVerificationRequest(BaseModel):
    """
    Request body for verifying that a given Deployment has rolled out
    successfully after a scale/restart/patch.
    """
    namespace: Optional[str] = Field(
        default=None,
        description="Kubernetes namespace where the deployment lives. "
                    "Defaults to SmartOps namespace if omitted.",
    )
    deployment: str = Field(
        ...,
        description="Kubernetes Deployment name.",
    )
    timeout_seconds: int = Field(
        default=60,
        ge=5,
        le=600,
        description="Maximum time to wait for rollout to complete.",
    )
    poll_interval_seconds: int = Field(
        default=5,
        ge=1,
        le=60,
        description="How often (in seconds) to poll the Deployment status.",
    )
    expected_replicas: Optional[int] = Field(
        default=None,
        description="Override desired replicas; defaults to deployment.spec.replicas if None.",
    )


class DeploymentVerificationResult(BaseModel):
    """
    Normalized result of a rollout verification check.
    This can be logged, displayed in Grafana, or fed back into AI/policy.
    """
    status: VerificationStatus
    message: str

    namespace: Optional[str] = None
    deployment: Optional[str] = None

    desired_replicas: Optional[int] = None
    ready_replicas: Optional[int] = None
    available_replicas: Optional[int] = None

    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional raw fields from the Kubernetes Deployment status.",
    )
