from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------- Incoming signals from AI (Kulathunga) ----------

class AnomalySignal(BaseModel):
    """
    This matches Kulathunga's anomaly JSON:
    {
      "windowId": "...",
      "service": "erp-simulator",
      "isAnomaly": true,
      "score": 0.90,
      "type": "latency",
      "modelVersion": "v1",
      "metadata": {}
    }
    """
    windowId: str
    service: str
    isAnomaly: bool
    score: float
    type: str
    modelVersion: Optional[str] = None

    # WHY: use default_factory so dict isn't shared across requests/instances
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RankedCause(BaseModel):
    """
    One item in RCA rankedCauses:
    {"svc": "erp-simulator", "cause": "memory_leak", "probability": 0.92}
    """
    svc: str
    cause: str
    probability: float


class RcaSignal(BaseModel):
    """
    This matches Kulathunga's RCA JSON:
    {
      "windowId": "...",
      "service": "erp-simulator",
      "rankedCauses": [...],
      "confidence": 0.88
    }
    """
    windowId: str
    service: str
    rankedCauses: List[RankedCause]
    confidence: float


# ---------- ActionPlan sent to Peiris's Orchestrator ----------

class Target(BaseModel):
    """
    Which Kubernetes object we want to affect.
    In your system this will be a Deployment in smartops-dev.
    """
    kind: str = "Deployment"
    namespace: str
    name: str


class ScaleSpec(BaseModel):
    """
    Extra data for scale actions.
    """
    replicas: int


class PatchSpec(BaseModel):
    """
    Extra data for patch actions (the JSON patch).
    """
    patch: Dict[str, Any]


class ActionPlan(BaseModel):
    """
    Unified action format that your Policy Engine produces,
    and Peiris's Orchestrator /v1/actions/execute will consume.
    """
    type: str  # "scale" | "restart" | "patch"
    dry_run: bool = False
    verify: bool = True
    target: Target
    scale: Optional[ScaleSpec] = None
    patch: Optional[PatchSpec] = None


# ---------- Policy DSL validations ----------

class PolicyValidateRequest(BaseModel):
    dsl: str


class PolicyValidateResponse(BaseModel):
    valid: bool
    policy_count: int = 0

    # WHY: use default_factory so list isn't shared across requests/instances
    errors: List[str] = Field(default_factory=list)


# ---------- Policy status / reload ----------

class PolicyStatusResponse(BaseModel):
    policy_file_path: str
    policy_count: int
    min_replicas: int
    max_replicas: int
    restart_cooldown_seconds: int


class PolicyReloadResponse(BaseModel):
    ok: bool
    policy_count: int
    source_path: str
    error: Optional[str] = None



# ---------- NEW: Audit log read models ----------

class PolicyAuditEvent(BaseModel):
    """
    WHY:
    - Flexible structure because audit events contain nested dicts.
    - We keep it as Dict[str, Any] to avoid over-complicating.
    """
    event: Dict[str, Any]


class PolicyAuditResponse(BaseModel):
    """
    Response for GET /v1/policy/audit
    """
    ok: bool
    log_path: str
    returned: int
    events: List[PolicyAuditEvent] = Field(default_factory=list)
    error: Optional[str] = None