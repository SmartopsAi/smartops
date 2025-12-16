from typing import List, Optional
from pydantic import BaseModel


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
    metadata: dict = {}


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
    patch: dict


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
