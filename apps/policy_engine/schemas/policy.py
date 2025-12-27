from __future__ import annotations

from pydantic import BaseModel
from typing import Any, Dict, Optional


class PolicyReloadResponse(BaseModel):
    ok: bool
    policy_count: int
    source_path: str
    error: Optional[str] = None


class EvaluateRequest(BaseModel):
    """
    Keep this aligned with what your /evaluate already expects.
    If you already have a schema file, you can merge this into it.
    """
    service: str
    anomaly: Optional[Dict[str, Any]] = None
    rca: Optional[Dict[str, Any]] = None


class EvaluateResponse(BaseModel):
    chosen_policy: Optional[str] = None
    action: Optional[Dict[str, Any]] = None
    blocked_by_guardrails: bool = False
    reason: Optional[str] = None
