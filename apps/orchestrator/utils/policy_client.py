from __future__ import annotations

import os
import json
import logging
from dataclasses import dataclass, asdict, is_dataclass
from enum import Enum
from typing import Optional, Any, Dict
from ..services.k8s_core import get_deployment_replicas, get_deployment_annotation

import httpx


logger = logging.getLogger("smartops.policy_client")


class PolicyDecisionType(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass
class PolicyDecision:
    decision: PolicyDecisionType
    reason: Optional[str] = None
    action_plan: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = None


class PolicyDecisionError(Exception):
    """Raised when the Policy Engine returns an invalid response or cannot be reached."""
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


def _to_dict(obj: Any) -> Dict[str, Any]:
    """
    Convert common Python/Pydantic objects to a plain dict safely.
    """
    if obj is None:
        return {}

    if isinstance(obj, dict):
        return obj

    # Pydantic v2
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass

    # Pydantic v1
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:
            pass

    # dataclass
    if is_dataclass(obj):
        try:
            return asdict(obj)
        except Exception:
            pass

    # fallback: object __dict__
    try:
        return dict(obj.__dict__)
    except Exception:
        return {}


def _extract_service(d: Dict[str, Any]) -> str:
    # Most common locations
    for k in ("service", "svc", "deployment", "app"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    # If nested raw incoming exists
    raw = d.get("raw") or {}
    incoming = raw.get("incoming") or {}
    v = incoming.get("service")
    if isinstance(v, str) and v.strip():
        return v.strip()

    return "erp-simulator"


def _normalize_signal_fields(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert various possible signal shapes into the DSL-required flat keys:
      anomaly.type, anomaly.score, rca.cause, rca.probability
    """
    out: Dict[str, Any] = {}

    # Case A: Already flat (preferred)
    for k in ("anomaly.type", "anomaly.score", "rca.cause", "rca.probability"):
        if k in d:
            out[k] = d[k]

    # Case B: Nested dict style (like your debug in policy-engine container)
    anomaly = d.get("anomaly")
    if isinstance(anomaly, dict):
        if "type" in anomaly and "anomaly.type" not in out:
            out["anomaly.type"] = anomaly.get("type")
        if "score" in anomaly and "anomaly.score" not in out:
            out["anomaly.score"] = anomaly.get("score")

    rca = d.get("rca")
    if isinstance(rca, dict):
        if "cause" in rca and "rca.cause" not in out:
            out["rca.cause"] = rca.get("cause")
        if "probability" in rca and "rca.probability" not in out:
            out["rca.probability"] = rca.get("probability")

    # Case C: Orchestrator models might use different field names
    # Try common alternates
    if "anomaly.type" not in out:
        for k in ("type", "anomaly_type", "anomalyType"):
            if k in d:
                out["anomaly.type"] = d.get(k)
                break

    if "anomaly.score" not in out:
        for k in ("score", "anomaly_score", "anomalyScore", "severity"):
            if k in d:
                out["anomaly.score"] = d.get(k)
                break

    if "rca.cause" not in out:
        # Some RCA signals come as rankedCauses[0].cause
        ranked = d.get("rankedCauses")
        if isinstance(ranked, list) and ranked:
            first = ranked[0]
            if isinstance(first, dict) and "cause" in first:
                out["rca.cause"] = first.get("cause")

        for k in ("cause", "root_cause", "rootCause"):
            if k in d and "rca.cause" not in out:
                out["rca.cause"] = d.get(k)
                break

    if "rca.probability" not in out:
        for k in ("probability", "confidence", "rca_probability", "rcaProbability"):
            if k in d:
                out["rca.probability"] = d.get(k)
                break

    # Final cleanup / defaults
    # Ensure numeric fields are numeric where possible
    if "anomaly.score" in out:
        try:
            out["anomaly.score"] = float(out["anomaly.score"])
        except Exception:
            pass

    if "rca.probability" in out:
        try:
            out["rca.probability"] = float(out["rca.probability"])
        except Exception:
            pass

    return out


SERVICE_TO_DEPLOYMENT = {
    "erp-simulator": "smartops-erp-simulator",
    "odoo": "odoo-web",
}
SMARTOPS_NS = os.getenv("SMARTOPS_NAMESPACE", "smartops-dev")


def _build_policy_payload(signal_obj: Any) -> Dict[str, Any]:
    """
    Policy Engine expects:
      {
        "service": "<name>",
        "signal": {
          "anomaly.type": "...",
          "anomaly.score": 1.0,
          "rca.cause": "...",
          "rca.probability": 0.95
        }
      }
    """
    d = _to_dict(signal_obj)

    # If caller already passed {"signal": {...}, "service": "..."} just keep it
    if isinstance(d.get("signal"), dict):
        service = d.get("service") or _extract_service(d)
        signal = _normalize_signal_fields(d["signal"])
        return {"service": service, "signal": signal}

    service = _extract_service(d)
    signal = _normalize_signal_fields(d)

    # Add current replica context (best-effort, never break policy check)
    try:
        dep = SERVICE_TO_DEPLOYMENT.get(service)
        if dep:
            cur = get_deployment_replicas(dep, SMARTOPS_NS)
            if cur is not None:
                signal["k8s.replicas.current"] = int(cur)

            # Stable remediation stage (do NOT infer from replicas.current)
            lvl_raw = get_deployment_annotation(dep, "smartops.io/remediation-level", SMARTOPS_NS)
            try:
                signal["remediation.level"] = int(lvl_raw) if lvl_raw is not None else 0
            except Exception:
                signal["remediation.level"] = 0

            # Optional baseline replicas (used for recovery / reset)
            base_raw = get_deployment_annotation(dep, "smartops.io/baseline-replicas", SMARTOPS_NS)
            try:
                if base_raw is not None:
                    signal["baseline.replicas"] = int(base_raw)
            except Exception:
                pass
    except Exception:
        pass

    return {"service": service, "signal": signal}


async def check_policy(signal_obj: Any) -> PolicyDecision:
    """
    Ask Policy Engine (DSL) whether remediation should happen.
    We POST the extracted signal payload.
    """
    url = f"{_policy_engine_base_url()}/v1/policy/evaluate"
    payload = _build_policy_payload(signal_obj)

    # 🔥 Debug output you NEED to see in logs
    logger.warning("POLICY_ENGINE payload=%s", json.dumps(payload, ensure_ascii=False))

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(url, json=payload)
    except Exception as exc:  # network, timeout, DNS, etc.
        raise PolicyDecisionError(f"Policy Engine unreachable: {exc}") from exc

    content_type = (resp.headers.get("content-type") or "").lower()
    if resp.status_code >= 400:
        raise PolicyDecisionError(f"Policy Engine HTTP {resp.status_code}: {resp.text[:200]}")
    if "application/json" not in content_type:
        raise PolicyDecisionError(f"Policy Engine returned non-JSON: {resp.text[:200]}")

    try:
        data = resp.json()
    except Exception as exc:
        raise PolicyDecisionError(f"Invalid JSON from Policy Engine: {exc}") from exc
    
    logger.warning("POLICY_ENGINE_RESPONSE=%s", json.dumps(data, ensure_ascii=False))
    
    pe_decision = (data.get("decision") or "").lower()
    reason = data.get("reason") or data.get("guardrail_reason") or None
    action_plan = data.get("action_plan")

    if pe_decision == "action" and action_plan:
        return PolicyDecision(
            decision=PolicyDecisionType.ALLOW,
            reason=reason,
            action_plan=action_plan,
            raw=data,
        )

    if pe_decision in {"blocked", "no_action"}:
        return PolicyDecision(
            decision=PolicyDecisionType.DENY,
            reason=reason or pe_decision,
            action_plan=None,
            raw=data,
        )

    raise PolicyDecisionError(f"Unexpected Policy Engine response: {data}")
