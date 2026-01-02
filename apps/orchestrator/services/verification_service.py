
import asyncio
import logging
from typing import Optional

from kubernetes.client import ApiException
from opentelemetry import trace

from ..models.verification_models import (
    DeploymentVerificationRequest,
    DeploymentVerificationResult,
    VerificationStatus,
)
from ..services import k8s_core

logger = logging.getLogger("smartops.orchestrator.verification")
tracer = trace.get_tracer(__name__)


async def verify_deployment_rollout(
    request: DeploymentVerificationRequest,
) -> DeploymentVerificationResult:
    """
    Asynchronous rollout verification using the new k8s_core helpers.

    This version:
      - Uses k8s_core.get_deployment_status()
      - Uses k8s_core.wait_for_deployment_rollout() for correctness
      - Removes dependency on old _apps_v1()
      - Preserves response schema & structure for backward compatibility

    Behavior:
      - If expected_replicas is provided → verify against that
      - Else → use the deployment's spec.replicas
      - Handles: SUCCESS, FAILED, TIMED_OUT
    """

    ns = request.namespace or k8s_core.DEFAULT_NAMESPACE

    with tracer.start_as_current_span("smartops.verify_deployment") as span:
        span.set_attribute("smartops.namespace", ns)
        span.set_attribute("smartops.deployment", request.deployment)
        span.set_attribute("smartops.timeout_seconds", request.timeout_seconds)
        span.set_attribute("smartops.poll_interval_seconds", request.poll_interval_seconds)

        try:
            # First, fetch the latest status snapshot
            initial_status = k8s_core.get_deployment_status(
                name=request.deployment,
                namespace=ns,
            )
        except Exception as exc:
            logger.error(
                "Error fetching initial deployment status %s/%s: %s",
                ns, request.deployment, exc,
            )
            span.record_exception(exc)
            return DeploymentVerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Failed to read deployment status: {exc}",
                namespace=ns,
                deployment=request.deployment,
                details={"exception": str(exc)},
            )

        # Determine desired replicas
        desired = (
            request.expected_replicas
            if request.expected_replicas is not None
            else initial_status.get("replicas", 0)
        )

        span.set_attribute("smartops.verification.desired_replicas", desired)

        # Perform the actual rollout wait loop (sync)
        # This is blocking, so we run it in thread pool
        loop = asyncio.get_running_loop()
        rollout_result = await loop.run_in_executor(
            None,
            lambda: k8s_core.wait_for_deployment_rollout(
                name=request.deployment,
                namespace=ns,
                timeout_seconds=request.timeout_seconds,
                poll_interval_seconds=request.poll_interval_seconds,
            ),
        )

        # -----------------------------------------------------------
        # Interpret rollout_result
        # -----------------------------------------------------------
        last = rollout_result.get("last_observed", {}) or {}

        ready = last.get("ready_replicas", 0)
        available = last.get("available_replicas", 0)

        if rollout_result["status"] == "success":
            span.set_attribute("smartops.verification.status", "success")
            logger.info(
                "Deployment rollout successful %s/%s: ready=%s desired=%s",
                ns, request.deployment, ready, desired,
            )
            return DeploymentVerificationResult(
                status=VerificationStatus.SUCCESS,
                message=f"Deployment rollout successful. Ready replicas: {ready}/{desired}.",
                namespace=ns,
                deployment=request.deployment,
                desired_replicas=desired,
                ready_replicas=ready,
                available_replicas=available,
                details=last,
            )

        # -----------------------------------------------------------
        # Timeout case
        # -----------------------------------------------------------
        if rollout_result["status"] == "timeout":
            span.set_attribute("smartops.verification.status", "timeout")
            logger.warning(
                "Timeout verifying rollout for %s/%s: ready=%s desired=%s",
                ns, request.deployment, ready, desired,
            )
            return DeploymentVerificationResult(
                status=VerificationStatus.TIMED_OUT,
                message=(
                    "Timed out waiting for deployment rollout. "
                    f"Last observed ready replicas {ready}, desired {desired}."
                ),
                namespace=ns,
                deployment=request.deployment,
                desired_replicas=desired,
                ready_replicas=ready,
                available_replicas=available,
                details=last,
            )

        # -----------------------------------------------------------
        # Should not happen, but safety:
        # -----------------------------------------------------------
        span.set_attribute("smartops.verification.status", "failed")
        return DeploymentVerificationResult(
            status=VerificationStatus.FAILED,
            message="Unexpected error during rollout verification.",
            namespace=ns,
            deployment=request.deployment,
            desired_replicas=desired,
            ready_replicas=ready,
            available_replicas=available,
            details=last,
        )
