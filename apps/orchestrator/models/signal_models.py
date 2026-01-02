from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field


class AnomalyType(str, Enum):
    LATENCY = "latency"
    ERROR = "error"
    RESOURCE = "resource"
    OTHER = "other"


class AnomalySignal(BaseModel):
    """
    Ingested from agent-detect.

    Expected to be compatible with something like:
      POST /v1/anomaly/predict {windowId, features[]} → {isAnomaly, score, type, modelVersion}
    """
    windowId: str
    service: str = Field(..., description="Service or deployment identifier.")
    isAnomaly: bool
    score: float
    type: AnomalyType = AnomalyType.OTHER
    modelVersion: Optional[str] = None
    tsRange: Optional[List[str]] = Field(
        default=None,
        description="Optional [start, end] timestamps for the detection window.",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RankedCause(BaseModel):
    svc: str
    cause: str
    probability: float


class RcaSignal(BaseModel):
    """
    Ingested from agent-diagnose.

      POST /v1/rca/diagnose {graph, signals} → {rankedCauses[], confidence, explanation}
    """
    windowId: str
    service: Optional[str] = None
    rankedCauses: List[RankedCause]
    confidence: float
    explanation: Optional[str] = None
    modelVersion: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
