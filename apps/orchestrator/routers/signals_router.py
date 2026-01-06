from __future__ import annotations

from typing import Dict, Any
import logging

from fastapi import APIRouter, HTTPException, status, Request
from opentelemetry import trace

from ..models.signal_models import AnomalySignal, RcaSignal
from ..models.action_models import ActionRequest
from ..services.signal_store import add_anomaly, add_rca, get_recent_signals
from ..services.closed_loop import closed_loop_manager
from ..utils.policy_client import (
    check_policy,
    PolicyDecisionType,
    PolicyDecisionError,
)

logger = logging.getLogger("smartops.signals")
tracer = trace.get_tracer(__name__)

router = APIRouter(
    prefix="/signals",
    tags=["signals"],
)

# ------------------------------------------------------------------------------
# Helper: Convert Pydantic model to pure dict (safe for JSON serialization)
# ------------------------------------------------------------------------------
def _signal_to_dict(signal: Any) -> Dict[str, Any]:
    try:
        return signal.model_dump()
    except Exception:
        return dict(signal)

# ------------------------------------------------------------------------------
# POST /signals/anomaly
# ------------------------------------------------------------------------------
@router.post(
    "/anomaly",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest anomaly signal (from agent-detect).",
    response_description="Signal accepted; remediation is policy-gated.",
)
async def ingest_anomaly(signal: AnomalySignal, request: Request) -> Dict[str, Any]:
    """
    Workflow:
        1. Accept + store signal (always)
        2. Ask Policy Engine if remediation is allowed
        3. If allowed → enqueue to ClosedLoopManager
        4. Return 202 immediately (non-blocking)
    """
    with tracer.start_as_current_span("signals.ingest_anomaly") as span:
        span.set_attribute("smartops.signal.windowId", signal.windowId)
        span.set_attribute("smartops.signal.service", signal.service)
        span.set_attribute("smartops.signal.type", signal.type.value)
        span.set_attribute("smartops.signal.score", signal.score)
        span.set_attribute("smartops.signal.isAnomaly", signal.isAnomaly)
        span.set_attribute("http.client_ip", request.client.host)

        try:
            # 1) Store signal (always)
            add_anomaly(signal)

            # 2) Policy Engine gate
            try:
                # NOTE:
                # Policy Engine evaluates runtime state (JSON files),
                # not this ActionRequest object. This is a formal trigger only.
                dummy_action = ActionRequest(
                    type=None,
                    target=None,
                    dry_run=False,
                    verify=True,
                )
                decision = await check_policy(dummy_action)

            except PolicyDecisionError as pe_exc:
                logger.error("Policy Engine error (anomaly): %s", pe_exc)
                span.set_attribute("smartops.policy.error", True)

                # Fail SAFE: accept signal, do NOT auto-remediate
                return {
                    "accepted": True,
                    "kind": "anomaly",
                    "windowId": signal.windowId,
                    "policy": "error",
                }

            # 3) Enqueue closed loop only if allowed
            if decision.decision == PolicyDecisionType.ALLOW:
                span.set_attribute("smartops.policy.decision", "allow")
                await closed_loop_manager.enqueue_anomaly(signal)
            else:
                span.set_attribute("smartops.policy.decision", "deny")
                logger.info(
                    "Policy blocked auto-remediation for anomaly windowId=%s reason=%s",
                    signal.windowId,
                    decision.reason,
                )

        except Exception as exc:
            logger.exception("Failed to process anomaly signal")
            span.record_exception(exc)
            raise HTTPException(
                status_code=500,
                detail=f"Error processing anomaly signal: {exc}",
            )

        return {
            "accepted": True,
            "kind": "anomaly",
            "windowId": signal.windowId,
        }

# ------------------------------------------------------------------------------
# POST /signals/rca
# ------------------------------------------------------------------------------
@router.post(
    "/rca",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest root-cause analysis signal (from agent-diagnose).",
    response_description="Signal accepted; remediation is policy-gated.",
)
async def ingest_rca(signal: RcaSignal, request: Request) -> Dict[str, Any]:
    """
    Workflow identical to anomaly ingestion, but for RCA signals.
    """
    with tracer.start_as_current_span("signals.ingest_rca") as span:
        span.set_attribute("smartops.signal.windowId", signal.windowId)
        span.set_attribute("smartops.signal.service", signal.service or "")
        span.set_attribute("smartops.signal.confidence", signal.confidence)
        span.set_attribute("smartops.signal.cause.count", len(signal.rankedCauses))
        span.set_attribute("http.client_ip", request.client.host)

        try:
            # 1) Store RCA (always)
            add_rca(signal)

            # 2) Policy Engine gate
            try:
                dummy_action = ActionRequest(
                    type=None,
                    target=None,
                    dry_run=False,
                    verify=True,
                )
                decision = await check_policy(dummy_action)

            except PolicyDecisionError as pe_exc:
                logger.error("Policy Engine error (RCA): %s", pe_exc)
                span.set_attribute("smartops.policy.error", True)

                return {
                    "accepted": True,
                    "kind": "rca",
                    "windowId": signal.windowId,
                    "policy": "error",
                }

            # 3) Enqueue closed loop only if allowed
            if decision.decision == PolicyDecisionType.ALLOW:
                span.set_attribute("smartops.policy.decision", "allow")
                await closed_loop_manager.enqueue_rca(signal)
            else:
                span.set_attribute("smartops.policy.decision", "deny")
                logger.info(
                    "Policy blocked auto-remediation for RCA windowId=%s reason=%s",
                    signal.windowId,
                    decision.reason,
                )

        except Exception as exc:
            logger.exception("Failed to process RCA signal")
            span.record_exception(exc)
            raise HTTPException(
                status_code=500,
                detail=f"Error processing RCA signal: {exc}",
            )

        return {
            "accepted": True,
            "kind": "rca",
            "windowId": signal.windowId,
        }

# ------------------------------------------------------------------------------
# GET /signals/recent
# ------------------------------------------------------------------------------
@router.get(
    "/recent",
    summary="Fetch in-memory recent anomaly + RCA signals.",
    description="Debug-only endpoint for dashboards.",
)
async def list_recent(limit: int = 20) -> Dict[str, Any]:
    with tracer.start_as_current_span("signals.list_recent") as span:
        span.set_attribute("smartops.limit", limit)

        try:
            anomalies, rcas = get_recent_signals(limit=limit)
        except Exception as exc:
            logger.exception("Failed to fetch recent signals")
            span.record_exception(exc)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to retrieve recent signals: {exc}",
            )

        span.set_attribute("smartops.anomaly.count", len(anomalies))
        span.set_attribute("smartops.rca.count", len(rcas))

        return {
            "limit": limit,
            "anomalies": anomalies,
            "rcas": rcas,
        }
