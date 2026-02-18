from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

@dataclass
class ServiceHealth:
    """Standardized health status for services (ERP, Orchestrator, etc.)"""
    name: str
    mode: str  # 'local' or 'k8s'
    status: str  # 'up', 'down', 'partial'
    last_seen: float  # Unix timestamp
    version: str = "unknown"
    # Key Performance Indicators
    error_rate: float = 0.0
    p95_latency_ms: float = 0.0
    rps: float = 0.0

@dataclass
class AnomalyEvent:
    """Represents a detection event from the Agent-Detect module"""
    ts: float
    service: str
    score: float
    anomaly_type: str
    model: str
    features_ref: Optional[str] = None  # Reference to feature snapshot ID

@dataclass
class FeatureSnapshot:
    """Feature importance data for the anomaly explanation"""
    ts: float
    window_id: str
    top_features: List[Dict[str, Any]] = field(default_factory=list)
    # Expected dict format: {'name': str, 'delta': float, 'value': float}

@dataclass
class RcaReport:
    """Root Cause Analysis output from Agent-Diagnose"""
    ts: float
    incident_id: str
    ranked_causes: List[Dict[str, Any]] = field(default_factory=list)
    # Expected dict: {'component': str, 'cause': str, 'confidence': float}
    evidence: Dict[str, List[str]] = field(default_factory=lambda: {"trace_ids": [], "logs": []})

@dataclass
class PolicyDecision:
    """Audit record of a policy evaluation"""
    ts: float
    policy_id: str
    decision: str  # 'allow' or 'block'
    reason: str
    guardrails: List[Dict[str, Any]] = field(default_factory=list)
    # Expected dict: {'name': str, 'triggered': bool}
    recommended_actions: List[str] = field(default_factory=list)

@dataclass
class ActionExecution:
    """History of a manual or automated action"""
    ts: float
    execution_id: str
    action_type: str  # 'scale' or 'restart'
    target: str  # namespace/deployment or pod
    params: Dict[str, Any]
    result: str  # 'success', 'failed', 'pending'
    duration_ms: float
    trace_id: Optional[str] = None

@dataclass
class VerificationResult:
    """Results of post-action verification checks"""
    ts: float
    execution_id: str
    checks: List[Dict[str, Any]] = field(default_factory=list)
    # Expected dict: {'name': str, 'passed': bool, 'expected': str, 'actual': str}
    overall: bool = False