"""
FastAPI router for SmartOps Orchestrator.

Exposes:
- POST /v1/k8s/scale
- POST /v1/k8s/restart
- POST /v1/actions/execute
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from opentelemetry import trace
from prometheus_client import Counter, Histogram, Gauge

# NOTE: Treat project root as "smartops" project, and orchestrator as a package under apps.
# So we import everything via apps.orchestrator.*
from ..models.action_models import (
    ScaleRequest,
    RestartRequest,
    ActionRequest,
    ActionResult,
    ActionType,
)
from ..models.verification_models import DeploymentVerificationRequest
from .verification_service import verify_deployment_rollout
from ..services.action_runner import ActionRunner
from ..services import k8s_core
from ..utils.name_resolver import resolve_deployment_name
from ..utils.policy_client import (
    check_policy,
    PolicyDecisionError,
)

router = APIRouter(tags=["orchestrator"])

logger = logging.getLogger("smartops.orchestrator")
tracer = trace.get_tracer(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics (high-cardinality: per action, namespace, deployment)
# ---------------------------------------------------------------------------

# Total actions executed via orchestrator (including /k8s/* + /actions/execute)
ORCH_ACTIONS_TOTAL = Counter(
    "smartops_orchestrator_actions_total",
    "Total orchestrator actions executed (including /k8s/* and /actions/execute).",
    [
        "source",      # k8s_scale, k8s_restart, actions_execute
        "action_type", # scale | restart | patch
        "namespace",
        "deployment",
        "status",      # success | failed | dry_run
        "dry_run",     # "true" | "false"
    ],
)

# Action execution latency
ORCH_ACTION_LATENCY_SECONDS = Histogram(
    "smartops_orchestrator_action_latency_seconds",
    "Latency of orchestrator actions (wrapper over ActionRunner).",
    [
        "source",
        "action_type",
        "namespace",
        "deployment",
        "status",
        "dry_run",
    ],
)

# Verification latency (for rollout checks)
ORCH_VERIFICATION_LATENCY_SECONDS = Histogram(
    "smartops_orchestrator_verification_latency_seconds",
    "Latency of deployment rollout verification invoked by orchestrator.",
    [
        "source",     # actions_execute_scale | actions_execute_restart | actions_execute_patch
        "namespace",
        "deployment",
        "status",     # SUCCESS | FAILED | TIMED_OUT
    ],
)

# Last action timestamp (for dashboards / auto-heal lines)
ORCH_LAST_ACTION_TIMESTAMP = Gauge(
    "smartops_orchestrator_last_action_timestamp",
    "Unix timestamp of the last orchestrator action.",
    [
        "source",
        "action_type",
        "namespace",
        "deployment",
        "status",
    ],
)

# ---------------------------------------------------------------------------
# Shared action runner instance
# ---------------------------------------------------------------------------

action_runner = ActionRunner()


def _format_target(namespace: Optional[str], name: str, kind: str = "Deployment") -> str:
    """
    Helper to create a human-readable target string.
    Uses SmartOps default namespace when not explicitly provided.
    """
    ns = namespace or k8s_core.DEFAULT_NAMESPACE
    return f"{kind} {ns}/{name}"


def _normalize_namespace(namespace: Optional[str]) -> str:
    """
    Normalize namespace for metrics and K8s calls.
    """
    return namespace or k8s_core.DEFAULT_NAMESPACE


def _record_action_metrics(
    *,
    source: str,
    action_type: str,
    namespace: str,
    deployment: str,
    status: str,
    dry_run: bool,
    duration_seconds: float,
) -> None:
    """
    Record orchestrator-level metrics for a single action.
    """
    ns = _normalize_namespace(namespace)
    dry = "true" if dry_run else "false"

    ORCH_ACTIONS_TOTAL.labels(
        source=source,
        action_type=action_type,
        namespace=ns,
        deployment=deployment,
        status=status,
        dry_run=dry,
    ).inc()

    ORCH_ACTION_LATENCY_SECONDS.labels(
        source=source,
        action_type=action_type,
        namespace=ns,
        deployment=deployment,
        status=status,
        dry_run=dry,
    ).observe(duration_seconds)

    # Gauge with last action timestamp (only for success/dry_run; still updated on failures)
    ORCH_LAST_ACTION_TIMESTAMP.labels(
        source=source,
        action_type=action_type,
        namespace=ns,
        deployment=deployment,
        status=status,
    ).set(time.time())


def _record_verification_metrics(
    *,
    source: str,
    namespace: str,
    deployment: str,
    status: str,
    duration_seconds: float,
) -> None:
    """
    Record verification latency metrics.
    """
    ns = _normalize_namespace(namespace)

    ORCH_VERIFICATION_LATENCY_SECONDS.labels(
        source=source,
        namespace=ns,
        deployment=deployment,
        status=status,
    ).observe(duration_seconds)


def _is_guardrail_error(result: Dict[str, Any]) -> bool:
    """
    Detect whether ActionRunner blocked the action due to replica guardrails.
    Relies on the standardized error message from ActionRunner.
    """
    if not result:
        return False
    if result.get("status") != "failed":
        return False
    err = result.get("error")
    if not err:
        return False
    return "Replica guardrail violated" in err


# ---------------------------------------------------------------------------
# Low-level convenience endpoints (K8s operations via Orchestrator)
# ---------------------------------------------------------------------------


@router.post("/k8s/scale", response_model=ActionResult)
def scale_deployment_endpoint(req: ScaleRequest) -> ActionResult:
    """
    Scale a Kubernetes Deployment.

    This is a low-level convenience endpoint mainly for tests & chaos integration.
    Under the hood it uses services.k8s_core + ActionRunner.

    Accepts friendly deployment names (e.g. 'erp-simulator') and resolves
    them to real names (e.g. 'smartops-erp-simulator').
    """
    source = "k8s_scale"
    ns = _normalize_namespace(req.namespace)

    # Resolve friendly name → real K8s deployment name
    resolved_name = resolve_deployment_name(req.deployment)
    target_str = _format_target(ns, resolved_name, kind="Deployment")

    with tracer.start_as_current_span("orchestrator.k8s.scale") as span:
        span.set_attribute("smartops.target", target_str)
        span.set_attribute("smartops.requested_name", req.deployment)
        span.set_attribute("smartops.resolved_name", resolved_name)
        span.set_attribute("smartops.replicas", req.replicas)
        span.set_attribute("smartops.dry_run", req.dry_run)

        # Execute action via ActionRunner
        result = action_runner.run(
            action_type="scale",
            action_fn=k8s_core.scale_deployment,
            dry_run=req.dry_run,
            target=target_str,
            name=resolved_name,
            replicas=req.replicas,
            namespace=ns,
        )

        status = result["status"]
        duration = result["duration_seconds"]

        # Prometheus metrics
        _record_action_metrics(
            source=source,
            action_type="scale",
            namespace=ns,
            deployment=resolved_name,
            status=status,
            dry_run=req.dry_run,
            duration_seconds=duration,
        )

        # Guardrail → HTTP 400
        if _is_guardrail_error(result):
            span.set_attribute("smartops.action.status", "guardrail_blocked")
            logger.warning(
                "Guardrail blocked scale for %s: %s",
                target_str,
                result["error"],
            )
            raise HTTPException(
                status_code=400,
                detail=result["error"],
            )

        if status == "failed":
            span.set_attribute("smartops.action.status", "failed")
            logger.error(
                "Failed to scale deployment %s: %s",
                target_str,
                result["error"],
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to scale deployment {target_str}: {result['error']}",
            )

        span.set_attribute("smartops.action.status", status)
        msg = f"Deployment {target_str} scaled to {req.replicas}"
        if req.dry_run:
            msg += " (dry-run)"

        logger.info(msg)

        return ActionResult(
            success=True,
            message=msg,
            dry_run=req.dry_run,
            details={"runner": result},
        )


@router.post("/k8s/restart", response_model=ActionResult)
def restart_deployment_endpoint(req: RestartRequest) -> ActionResult:
    """
    Trigger a rolling restart by patching a dummy annotation on pod template.
    Uses services.k8s_core + ActionRunner.

    Accepts friendly deployment names and resolves them to real K8s names.
    """
    source = "k8s_restart"
    ns = _normalize_namespace(req.namespace)

    resolved_name = resolve_deployment_name(req.deployment)
    target_str = _format_target(ns, resolved_name, kind="Deployment")
    now_str = datetime.datetime.utcnow().isoformat() + "Z"

    with tracer.start_as_current_span("orchestrator.k8s.restart") as span:
        span.set_attribute("smartops.target", target_str)
        span.set_attribute("smartops.requested_name", req.deployment)
        span.set_attribute("smartops.resolved_name", resolved_name)
        span.set_attribute("smartops.dry_run", req.dry_run)
        span.set_attribute("smartops.requested_at", now_str)

        result = action_runner.run(
            action_type="restart",
            action_fn=k8s_core.restart_deployment,
            dry_run=req.dry_run,
            target=target_str,
            name=resolved_name,
            namespace=ns,
        )

        status = result["status"]
        duration = result["duration_seconds"]

        # Prometheus metrics
        _record_action_metrics(
            source=source,
            action_type="restart",
            namespace=ns,
            deployment=resolved_name,
            status=status,
            dry_run=req.dry_run,
            duration_seconds=duration,
        )

        if status == "failed":
            span.set_attribute("smartops.action.status", "failed")
            logger.error(
                "Failed to restart deployment %s: %s",
                target_str,
                result["error"],
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to restart deployment {target_str}: {result['error']}",
            )

        span.set_attribute("smartops.action.status", status)
        msg = f"Deployment {target_str} restart triggered at {now_str}"
        if req.dry_run:
            msg += " (dry-run)"

        logger.info(msg)

        return ActionResult(
            success=True,
            message=msg,
            dry_run=req.dry_run,
            details={"runner": result},
        )


# ---------------------------------------------------------------------------
# High-level Policy/AI Action Endpoint
# ---------------------------------------------------------------------------


@router.post("/actions/execute", response_model=ActionResult)
async def execute_action(req: ActionRequest) -> ActionResult:
    """
    High-level action executor endpoint.

    This is what Policy Engine and AI agents will call:
      - type: scale | restart | patch
      - target: { kind, namespace, name }
      - scale: { replicas } (for type=scale)
      - patch: { patch: {...} } (for type=patch)

    Now implemented using:
      - services.k8s_core
      - services.action_runner.ActionRunner
      - optional automatic rollout verification
      - Policy Engine guardrails (for non-dry-run requests)

    Supports friendly target names (e.g. 'erp-simulator') and resolves them
    to real deployment names (e.g. 'smartops-erp-simulator').
    """
    source_base = "actions_execute"
    # Resolve the target deployment name (friendly → real)
    requested_name = req.target.name
    resolved_name = resolve_deployment_name(requested_name)
    ns = _normalize_namespace(req.target.namespace)
    kind = req.target.kind

    # Use resolved name in target string
    target_str = _format_target(ns, resolved_name, kind)

    with tracer.start_as_current_span("orchestrator.actions.execute") as span:
        span.set_attribute("smartops.action.type", req.type.value)
        span.set_attribute("smartops.action.target", target_str)
        span.set_attribute("smartops.action.dry_run", req.dry_run)
        span.set_attribute("smartops.action.verify", req.verify)
        span.set_attribute("smartops.requested_name", requested_name)
        span.set_attribute("smartops.resolved_name", resolved_name)
        if req.reason:
            span.set_attribute("smartops.action.reason", req.reason)

        # ------------------------------------------------------------------
        # Policy Engine guardrail (only for non-dry-run requests)
        # ------------------------------------------------------------------
        if not req.dry_run:
            try:
                decision = await check_policy(req)
            except PolicyDecisionError as exc:
                span.set_attribute("smartops.policy.status", "error")
                logger.error(
                    "Policy Engine error for %s %s: %s",
                    req.type.value,
                    target_str,
                    exc,
                )
                raise HTTPException(
                    status_code=502,
                    detail=f"Policy Engine error: {exc}",
                )

            allowed = decision.get("allow", True)
            span.set_attribute("smartops.policy.allowed", allowed)
            span.set_attribute(
                "smartops.policy.decision",
                decision.get("decision", "unknown"),
            )
            if not allowed:
                reason = decision.get("reason", "Blocked by policy")
                logger.warning(
                    "Policy Engine denied action %s on %s: %s",
                    req.type.value,
                    target_str,
                    reason,
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Action blocked by policy engine: {reason}",
                )

        verification = None

        # ---------------- SCALE ----------------
        if req.type == ActionType.SCALE:
            if not req.scale:
                raise HTTPException(400, "scale parameters are required for SCALE action")

            result = action_runner.run(
                action_type="scale",
                action_fn=k8s_core.scale_deployment,
                dry_run=req.dry_run,
                target=target_str,
                name=resolved_name,
                replicas=req.scale.replicas,
                namespace=ns,
            )

            status = result["status"]
            duration = result["duration_seconds"]

            # Orchestrator metrics: SCALE via /actions/execute
            _record_action_metrics(
                source=f"{source_base}_scale",
                action_type="scale",
                namespace=ns,
                deployment=resolved_name,
                status=status,
                dry_run=req.dry_run,
                duration_seconds=duration,
            )

            # Guardrail → HTTP 400 (replica-level)
            if _is_guardrail_error(result):
                span.set_attribute("smartops.action.status", "guardrail_blocked")
                logger.warning(
                    "Guardrail blocked SCALE %s: %s",
                    target_str,
                    result["error"],
                )
                raise HTTPException(
                    status_code=400,
                    detail=result["error"],
                )

            if status == "failed":
                span.set_attribute("smartops.action.status", "failed")
                raise HTTPException(500, f"Failed SCALE action: {result['error']}")

            # Auto-verification (only if not dry_run)
            if req.verify and not req.dry_run:
                vreq = DeploymentVerificationRequest(
                    namespace=ns,
                    deployment=resolved_name,
                    timeout_seconds=req.verify_timeout_seconds,
                    poll_interval_seconds=req.verify_poll_interval_seconds,
                    expected_replicas=req.scale.replicas,
                )

                ver_start = time.monotonic()
                verification = await verify_deployment_rollout(vreq)
                ver_duration = time.monotonic() - ver_start

                span.set_attribute("smartops.verification.status", verification.status.value)

                # Verification metrics
                _record_verification_metrics(
                    source=f"{source_base}_scale",
                    namespace=ns,
                    deployment=resolved_name,
                    status=verification.status.value,
                    duration_seconds=ver_duration,
                )

            span.set_attribute("smartops.action.status", status)
            msg = (
                f"SCALE {target_str} -> {req.scale.replicas}"
                + (" (dry-run)" if req.dry_run else "")
            )
            return ActionResult(
                success=True,
                message=msg,
                dry_run=req.dry_run,
                details={"runner": result},
                verification=verification,
            )

        # ---------------- RESTART ----------------
        elif req.type == ActionType.RESTART:
            now_str = datetime.datetime.utcnow().isoformat() + "Z"

            result = action_runner.run(
                action_type="restart",
                action_fn=k8s_core.restart_deployment,
                dry_run=req.dry_run,
                target=target_str,
                name=resolved_name,
                namespace=ns,
            )

            status = result["status"]
            duration = result["duration_seconds"]

            # Orchestrator metrics: RESTART via /actions/execute
            _record_action_metrics(
                source=f"{source_base}_restart",
                action_type="restart",
                namespace=ns,
                deployment=resolved_name,
                status=status,
                dry_run=req.dry_run,
                duration_seconds=duration,
            )

            if status == "failed":
                span.set_attribute("smartops.action.status", "failed")
                raise HTTPException(500, f"Failed RESTART action: {result['error']}")

            if req.verify and not req.dry_run:
                vreq = DeploymentVerificationRequest(
                    namespace=ns,
                    deployment=resolved_name,
                    timeout_seconds=req.verify_timeout_seconds,
                    poll_interval_seconds=req.verify_poll_interval_seconds,
                    expected_replicas=None,  # infer from Deployment spec
                )

                ver_start = time.monotonic()
                verification = await verify_deployment_rollout(vreq)
                ver_duration = time.monotonic() - ver_start

                span.set_attribute("smartops.verification.status", verification.status.value)

                # Verification metrics
                _record_verification_metrics(
                    source=f"{source_base}_restart",
                    namespace=ns,
                    deployment=resolved_name,
                    status=verification.status.value,
                    duration_seconds=ver_duration,
                )

            span.set_attribute("smartops.action.status", status)
            msg = (
                f"RESTART {target_str} triggered at {now_str}"
                + (" (dry-run)" if req.dry_run else "")
            )
            return ActionResult(
                success=True,
                message=msg,
                dry_run=req.dry_run,
                details={"runner": result},
                verification=verification,
            )

        # ---------------- PATCH ----------------
        elif req.type == ActionType.PATCH:
            if not req.patch:
                raise HTTPException(400, "patch parameters are required for PATCH action")

            result = action_runner.run(
                action_type="patch",
                action_fn=k8s_core.patch_deployment,
                dry_run=req.dry_run,
                target=target_str,
                name=resolved_name,
                patch_body=req.patch.patch,
                namespace=ns,
            )

            status = result["status"]
            duration = result["duration_seconds"]

            # Orchestrator metrics: PATCH via /actions/execute
            _record_action_metrics(
                source=f"{source_base}_patch",
                action_type="patch",
                namespace=ns,
                deployment=resolved_name,
                status=status,
                dry_run=req.dry_run,
                duration_seconds=duration,
            )

            if status == "failed":
                span.set_attribute("smartops.action.status", "failed")
                raise HTTPException(500, f"Failed PATCH action: {result['error']}")

            if req.verify and not req.dry_run:
                vreq = DeploymentVerificationRequest(
                    namespace=ns,
                    deployment=resolved_name,
                    timeout_seconds=req.verify_timeout_seconds,
                    poll_interval_seconds=req.verify_poll_interval_seconds,
                    expected_replicas=None,
                )

                ver_start = time.monotonic()
                verification = await verify_deployment_rollout(vreq)
                ver_duration = time.monotonic() - ver_start

                span.set_attribute("smartops.verification.status", verification.status.value)

                # Verification metrics
                _record_verification_metrics(
                    source=f"{source_base}_patch",
                    namespace=ns,
                    deployment=resolved_name,
                    status=verification.status.value,
                    duration_seconds=ver_duration,
                )

            span.set_attribute("smartops.action.status", status)
            msg = (
                f"PATCH {target_str}"
                + (" (dry-run)" if req.dry_run else "")
            )
            return ActionResult(
                success=True,
                message=msg,
                dry_run=req.dry_run,
                details={"runner": result},
                verification=verification,
            )

        else:
            raise HTTPException(400, f"Unsupported action type: {req.type}")
