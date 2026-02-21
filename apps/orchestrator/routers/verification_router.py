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
      • Tries the provided name as-is first (supports real K8s names like 'odoo-web', 'smartops-erp-simulator')
      • Falls back to name resolver (friendly → real) if needed (e.g., 'erp-simulator' → 'smartops-erp-simulator')
      • Adds OTEL tracing
      • Returns structured response (success/timeout/failure) when possible
      • Raises structured HTTP errors on internal failure
    """
    namespace = request.namespace or DEFAULT_NAMESPACE
    original_name = request.deployment

    with tracer.start_as_current_span("verification.deployment") as span:
        span.set_attribute("smartops.namespace", namespace)
        span.set_attribute("smartops.deployment.requested", original_name)
        span.set_attribute("http.client_ip", http.client.host if http.client else "")
        span.set_attribute("smartops.timeout_seconds", request.timeout_seconds)
        span.set_attribute("smartops.poll_interval_seconds", request.poll_interval_seconds)

        # ------------------------------------------------------------------
        # 1. Resolve name (friendly → real), but NEVER fail early
        #    Strategy:
        #      - Try verifying the name as-is (it might already be real)
        #      - If needed, fallback to resolver mapping
        # ------------------------------------------------------------------
        resolved_name = original_name
        try:
            candidate = resolve_deployment_name(original_name)
            if candidate and isinstance(candidate, str):
                resolved_name = candidate
        except Exception as exc:
            # Do NOT raise 404 here; verification may still succeed with original name.
            logger.warning(
                "Name resolver failed for '%s' (will try direct name). error=%s",
                original_name,
                exc,
            )

        span.set_attribute("smartops.deployment.resolved", resolved_name)

        # ------------------------------------------------------------------
        # 2. Perform verification (try original name first, then resolved fallback)
        # ------------------------------------------------------------------
        try:
            # Attempt 1: treat provided name as the real Deployment name
            request.deployment = original_name
            result = await verify_deployment_rollout(request)

            span.set_attribute("smartops.verification.status", result.status.value)
            span.set_attribute("smartops.replicas.desired", result.desired_replicas or -1)
            span.set_attribute("smartops.replicas.ready", result.ready_replicas or -1)
            return result

        except Exception as first_exc:
            # Attempt 2: try resolver output if different from original
            if resolved_name != original_name:
                try:
                    request.deployment = resolved_name
                    result = await verify_deployment_rollout(request)

                    span.set_attribute("smartops.verification.status", result.status.value)
                    span.set_attribute("smartops.replicas.desired", result.desired_replicas or -1)
                    span.set_attribute("smartops.replicas.ready", result.ready_replicas or -1)
                    return result
                except Exception as second_exc:
                    logger.exception(
                        "Verification failed for both names: '%s' and '%s'",
                        original_name,
                        resolved_name,
                    )
                    span.record_exception(second_exc)
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Verification failed for '{original_name}' and '{resolved_name}': {second_exc}",
                    )

            # If resolver gave the same name (or didn't help), surface original error
            logger.exception("Internal error during deployment verification")
            span.record_exception(first_exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Verification failed due to internal error: {first_exc}",
            )
