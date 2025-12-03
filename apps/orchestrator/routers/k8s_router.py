from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from opentelemetry import trace

from ..services.action_runner import ActionRunner
from ..services import k8s_core
from ..services.k8s_core import (
    list_pods,
    list_deployments,
)
from ..utils.name_resolver import resolve_deployment_name

router = APIRouter(
    prefix="/k8s",
    tags=["kubernetes"],
)

tracer = trace.get_tracer(__name__)
action_runner = ActionRunner()


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class ScaleRequest(BaseModel):
    namespace: Optional[str] = Field(
        default=None,
        description="Kubernetes namespace (defaults to SmartOps namespace).",
    )
    replicas: int = Field(
        gt=0,
        description="Desired number of replicas (must be > 0).",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, Kubernetes server-side dry-run will be used.",
    )


class PatchRequest(BaseModel):
    namespace: Optional[str] = Field(
        default=None,
        description="Kubernetes namespace (defaults to SmartOps namespace).",
    )
    patch: Dict[str, Any] = Field(
        ...,
        description="Partial Deployment spec to apply as a strategic merge patch.",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, Kubernetes server-side dry-run will be used.",
    )


# ---------------------------------------------------------------------------
# List Pods
# ---------------------------------------------------------------------------

@router.get("/pods")
async def get_pods(
    namespace: Optional[str] = Query(default=None),
    label_selector: Optional[str] = Query(default=None),
):
    """
    List pods in the cluster for a given namespace and optional label selector.
    """
    with tracer.start_as_current_span("router.k8s.get_pods"):
        try:
            items = list_pods(namespace=namespace, label_selector=label_selector)
            return {"items": items}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# List Deployments
# ---------------------------------------------------------------------------

@router.get("/deployments")
async def get_deployments(
    namespace: Optional[str] = Query(default=None),
    label_selector: Optional[str] = Query(default=None),
):
    """
    List deployments in the given namespace.
    """
    with tracer.start_as_current_span("router.k8s.get_deployments"):
        try:
            items = list_deployments(namespace=namespace, label_selector=label_selector)
            return {"items": items}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Scale Deployment
# ---------------------------------------------------------------------------

@router.post("/scale/{deployment_name}")
async def scale(
    deployment_name: str,
    body: ScaleRequest,
):
    """
    Scale a deployment to a specific replica count.
    Accepts friendly names (e.g., 'erp-simulator') and resolves them to
    real deployment names (e.g., 'smartops-erp-simulator').
    """
    ns = body.namespace or k8s_core.DEFAULT_NAMESPACE
    resolved_name = resolve_deployment_name(deployment_name)
    target = f"Deployment {ns}/{resolved_name}"

    with tracer.start_as_current_span("router.k8s.scale") as span:
        span.set_attribute("smartops.target", target)
        span.set_attribute("smartops.replicas", body.replicas)
        span.set_attribute("smartops.dry_run", body.dry_run)
        span.set_attribute("smartops.requested_name", deployment_name)
        span.set_attribute("smartops.resolved_name", resolved_name)

        result = action_runner.run(
            action_type="scale",
            action_fn=k8s_core.scale_deployment,
            dry_run=body.dry_run,
            target=target,
            name=resolved_name,
            replicas=body.replicas,
            namespace=ns,
        )

        if result["status"] == "failed":
            raise HTTPException(
                status_code=500,
                detail=f"Failed to scale {target}: {result['error']}",
            )

        return {
            "status": result["status"],
            "operation": "scale",
            "deployment": result,
        }


# ---------------------------------------------------------------------------
# Restart Deployment
# ---------------------------------------------------------------------------

@router.post("/restart/{deployment_name}")
async def restart(
    deployment_name: str,
    namespace: Optional[str] = Query(default=None),
    dry_run: Optional[bool] = Query(default=False),
):
    """
    Trigger a rolling restart of a deployment (kubectl rollout restart style).
    Accepts friendly names and resolves them to real K8s names.
    """
    ns = namespace or k8s_core.DEFAULT_NAMESPACE
    resolved_name = resolve_deployment_name(deployment_name)
    target = f"Deployment {ns}/{resolved_name}"

    with tracer.start_as_current_span("router.k8s.restart") as span:
        span.set_attribute("smartops.target", target)
        span.set_attribute("smartops.dry_run", dry_run)
        span.set_attribute("smartops.requested_name", deployment_name)
        span.set_attribute("smartops.resolved_name", resolved_name)

        result = action_runner.run(
            action_type="restart",
            action_fn=k8s_core.restart_deployment,
            dry_run=dry_run,
            target=target,
            name=resolved_name,
            namespace=ns,
        )

        if result["status"] == "failed":
            raise HTTPException(
                status_code=500,
                detail=f"Failed to restart {target}: {result['error']}",
            )

        return {
            "status": result["status"],
            "operation": "restart",
            "deployment": result,
        }


# ---------------------------------------------------------------------------
# Patch Deployment
# ---------------------------------------------------------------------------

@router.post("/patch/{deployment_name}")
async def patch(
    deployment_name: str,
    body: PatchRequest,
):
    """
    Apply a generic patch to a deployment.
    WARNING: Powerful operation; in SmartOps this will be driven by Policy Engine guardrails.
    Accepts friendly names and resolves them to real K8s names.
    """
    ns = body.namespace or k8s_core.DEFAULT_NAMESPACE
    resolved_name = resolve_deployment_name(deployment_name)
    target = f"Deployment {ns}/{resolved_name}"

    with tracer.start_as_current_span("router.k8s.patch") as span:
        span.set_attribute("smartops.target", target)
        span.set_attribute("smartops.dry_run", body.dry_run)
        span.set_attribute("smartops.requested_name", deployment_name)
        span.set_attribute("smartops.resolved_name", resolved_name)

        result = action_runner.run(
            action_type="patch",
            action_fn=k8s_core.patch_deployment,
            dry_run=body.dry_run,
            target=target,
            name=resolved_name,
            patch_body=body.patch,
            namespace=ns,
        )

        if result["status"] == "failed":
            raise HTTPException(
                status_code=500,
                detail=f"Failed to patch {target}: {result['error']}",
            )

        return {
            "status": result["status"],
            "operation": "patch",
            "deployment": result,
        }
