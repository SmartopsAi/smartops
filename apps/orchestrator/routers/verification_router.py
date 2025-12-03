from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException, status, Request
from opentelemetry import trace

from ..models.verification_models import (
    DeploymentVerificationRequest,
    DeploymentVerificationResult,
)
from ..services.verification_service import verify_deployment_rollout
from ..utils.name_resolver import resolve_deployment_name
from ..services.k8s_core import DEFAULT_NAMESPACE

logger = logging.getLogger("smartops.verification")
tracer = trace.get_tracer(__name__)

router = APIRouter(
    prefix="/verify",
    tags=["verification"],
)


@router.post(
    "/deployment",
    response_model=DeploymentVerificationResult,
    summary="Verify Kubernetes Deployment rollout status.",
    description=(
        "Verifies that a Deployment has reached the desired rollout state.\n"
        "Works for both scale and restart operations.\n"
        "Compatible with Policy Engine, Closed Loop, and Chaos Testing."
    ),
)
async def verify_deployment(
    request: DeploymentVerificationRequest,
    http: Request,
) -> DeploymentVerificationResult:
    """
    Verify a Deployment has:
      - the desired number of replicas
      - updated/ready/available replicas matching expectations
      - or returns TIMEOUT/FAILURE with meaningful diagnostics

    Behavior:
      • Applies name resolver (user-friendly → real K8s name)
      • Enforces namespace defaulting rules
      • Adds OTEL tracing
      • Raises structured HTTP errors on internal failure
    """
    namespace = request.namespace or DEFAULT_NAMESPACE
    original_name = request.deployment

    with tracer.start_as_current_span("verification.deployment") as span:
        span.set_attribute("smartops.namespace", namespace)
        span.set_attribute("smartops.deployment.requested", original_name)
        span.set_attribute("http.client_ip", http.client.host)
        span.set_attribute("smartops.timeout_seconds", request.timeout_seconds)
        span.set_attribute("smartops.poll_interval_seconds", request.poll_interval_seconds)

        # ------------------------------------------------------------------
        # 1. Resolve name (friendly → real)
        # ------------------------------------------------------------------
        try:
            resolved_name = resolve_deployment_name(original_name)
            request.deployment = resolved_name

            span.set_attribute("smartops.deployment.resolved", resolved_name)
            logger.info(
                "Verification request resolved %s → %s",
                original_name,
                resolved_name,
            )
        except Exception as exc:
            logger.exception("Failed to resolve deployment name: %s", original_name)
            span.record_exception(exc)
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Deployment '{original_name}' not found in namespace '{namespace}'.",
            )

        # ------------------------------------------------------------------
        # 2. Perform verification
        # ------------------------------------------------------------------
        try:
            result = await verify_deployment_rollout(request)

            # Attach OTEL info
            span.set_attribute("smartops.verification.status", result.status.value)
            span.set_attribute("smartops.replicas.desired", result.desired_replicas or -1)
            span.set_attribute("smartops.replicas.ready", result.ready_replicas or -1)

            # Success OR timeout OR failure → always return 200 with structured body
            return result

        except Exception as exc:
            logger.exception("Internal error during deployment verification")
            span.record_exception(exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Verification failed due to internal error: {exc}",
            )
