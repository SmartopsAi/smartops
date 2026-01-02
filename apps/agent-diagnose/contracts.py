from dataclasses import dataclass
from typing import List, Dict

@dataclass
class RCAEvidence:
    metrics: List[str]
    logs: List[str]
    traces: List[str]

@dataclass
class RCARootCause:
    component: str
    type: str
    signal: str

@dataclass
class RCAReport:
    anomaly_id: str
    timestamp: str
    detected_anomaly: str
    root_cause: RCARootCause
    evidence: RCAEvidence
    confidence: float
