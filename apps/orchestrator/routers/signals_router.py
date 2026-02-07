from __future__ import annotations

import logging
from typing import Dict, Any

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
# POST /signals/anomaly
# ------------------------------------------------------------------------------
@router.post(
    "/anomaly",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest anomaly signal (from agent-detect).",
)
async def ingest_anomaly(signal: AnomalySignal, request: Request) -> Dict[str, Any]:
    """
    Correct workflow (production-safe):

    1. Store anomaly signal
    2. Enqueue into ClosedLoopManager
    3. Closed loop will:
        - call Policy Engine
        - build ActionRequest
        - execute if allowed
    """
    with tracer.start_as_current_span("signals.ingest_anomaly") as span:
        try:
            span.set_attribute("smartops.signal.windowId", signal.windowId)
            span.set_attribute("smartops.signal.service", signal.service)
            span.set_attribute("smartops.signal.type", signal.type.value)
            span.set_attribute("smartops.signal.score", signal.score)
            span.set_attribute("smartops.signal.isAnomaly", signal.isAnomaly)
            span.set_attribute("http.client_ip", request.client.host)

            # 1) Store signal
            add_anomaly(signal)

            # 2) Enqueue for closed-loop processing
            await closed_loop_manager.enqueue_anomaly(signal)

            return {
                "accepted": True,
                "kind": "anomaly",
                "windowId": signal.windowId,
                "enqueued": True,
            }

        except Exception as exc:
            logger.exception("Failed to process anomaly signal")
            span.record_exception(exc)
            raise HTTPException(
                status_code=500,
                detail=f"Error processing anomaly signal: {exc}",
            )

# ------------------------------------------------------------------------------
# POST /signals/rca
# ------------------------------------------------------------------------------
@router.post(
    "/rca",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest RCA signal (from agent-diagnose).",
)
async def ingest_rca(signal: RcaSignal, request: Request) -> Dict[str, Any]:
    with tracer.start_as_current_span("signals.ingest_rca") as span:
        try:
            span.set_attribute("smartops.signal.windowId", signal.windowId)
            span.set_attribute("smartops.signal.service", signal.service or "")
            span.set_attribute("smartops.signal.confidence", signal.confidence)
            span.set_attribute("http.client_ip", request.client.host)

            add_rca(signal)
            await closed_loop_manager.enqueue_rca(signal)

            return {
                "accepted": True,
                "kind": "rca",
                "windowId": signal.windowId,
                "enqueued": True,
            }

        except Exception as exc:
            logger.exception("Failed to process RCA signal")
            span.record_exception(exc)
            raise HTTPException(
                status_code=500,
                detail=f"Error processing RCA signal: {exc}",
            )

# ------------------------------------------------------------------------------
# GET /signals/recent
# ------------------------------------------------------------------------------
@router.get(
    "/recent",
    summary="Fetch recent anomaly + RCA signals (debug).",
)
async def list_recent(limit: int = 20) -> Dict[str, Any]:
    try:
        anomalies, rcas = get_recent_signals(limit=limit)
        return {
            "limit": limit,
            "anomalies": anomalies,
            "rcas": rcas,
        }
    except Exception as exc:
        logger.exception("Failed to fetch recent signals")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve recent signals: {exc}",
        )
