from __future__ import annotations

from typing import Dict, Any, Tuple, List
import logging

from fastapi import APIRouter, HTTPException, status, Request
from opentelemetry import trace

from ..models.signal_models import AnomalySignal, RcaSignal
from ..services.signal_store import add_anomaly, add_rca, get_recent_signals
from ..services.closed_loop import closed_loop_manager

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
        # fallback (should not normally be needed)
        return dict(signal)


# ------------------------------------------------------------------------------
# POST /signals/anomaly
# ------------------------------------------------------------------------------
@router.post(
    "/anomaly",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest anomaly signal (from agent-detect).",
    response_description="Signal accepted and forwarded to closed-loop.",
)
async def ingest_anomaly(signal: AnomalySignal, request: Request) -> Dict[str, Any]:
    """
    Receives anomaly detection results.

    Workflow:
        1. Validate schema (via Pydantic)
        2. Add to in-memory signal store (for debugging/dashboards)
        3. Forward into ClosedLoopManager queue
        4. Immediately return 202 (non-blocking)

    This endpoint must remain:
        • NON-BLOCKING
        • High-throughput
        • Low latency

    Closed-loop work happens asynchronously.
    """
    with tracer.start_as_current_span("signals.ingest_anomaly") as span:
        span.set_attribute("smartops.signal.windowId", signal.windowId)
        span.set_attribute("smartops.signal.service", signal.service)
        span.set_attribute("smartops.signal.type", signal.type.value)
        span.set_attribute("smartops.signal.score", signal.score)
        span.set_attribute("smartops.signal.isAnomaly", signal.isAnomaly)
        span.set_attribute("http.client_ip", request.client.host)

        try:
            # Store for debug/dashboard
            add_anomaly(signal)

            # Send to closed-loop queue
            await closed_loop_manager.enqueue_anomaly(signal)

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
    response_description="RCA signal accepted and forwarded to closed-loop.",
)
async def ingest_rca(signal: RcaSignal, request: Request) -> Dict[str, Any]:
    """
    Receives RCA outputs from agent-diagnose.

    Typical input structure:
        {
          "windowId": "t1",
          "service": "erp-simulator",
          "rankedCauses": [ ... ],
          "confidence": 0.87
        }

    Closed-loop engine determines which RCA → remediation mapping applies.
    """
    with tracer.start_as_current_span("signals.ingest_rca") as span:
        span.set_attribute("smartops.signal.windowId", signal.windowId)
        span.set_attribute("smartops.signal.service", signal.service or "")
        span.set_attribute("smartops.signal.confidence", signal.confidence)
        span.set_attribute("smartops.signal.cause.count", len(signal.rankedCauses))
        span.set_attribute("http.client_ip", request.client.host)

        try:
            add_rca(signal)
            await closed_loop_manager.enqueue_rca(signal)

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
    description=(
        "Lightweight debugging endpoint. "
        "In production, this should be accessible only to internal dashboards."
    ),
)
async def list_recent(limit: int = 20) -> Dict[str, Any]:
    """
    Provides recent:
      - anomaly signals
      - rca signals

    For debugging and dashboard integration.

    This is NOT a production persistence layer.
    """
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
