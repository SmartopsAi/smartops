import asyncio
import os
import logging
import requests
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

PROMETHEUS_API = os.getenv(
    "PROMETHEUS_API",
    "http://kps-kube-prometheus-stack-prometheus.monitoring:9090/api/v1/query",
)

# ERP KPI success thresholds (demo-safe)
ERP_P95_LATENCY_OK = 1.2    # seconds
ERP_5XX_RATE_OK = 0.1       # req/s

ODOO_INGRESS_HOST = os.getenv("ODOO_INGRESS_HOST", "odoo.localhost")
SMARTOPS_NAMESPACE = os.getenv("SMARTOPS_NAMESPACE", "smartops-dev")


def query_prometheus(promql: str) -> float:
    resp = requests.get(PROMETHEUS_API, params={"query": promql}, timeout=5)
    resp.raise_for_status()
    data = resp.json()["data"]["result"]
    if not data:
        return 0.0
    return float(data[0]["value"][1])


def verify_erp_kpis() -> bool:
    """
    Verify ERP health after an action using Prometheus KPIs.
    """
    latency = query_prometheus(
        f"""
        histogram_quantile(
          0.95,
          sum by (le) (
            rate(
              nginx_ingress_controller_request_duration_seconds_bucket{
                host="{ODOO_INGRESS_HOST}",
                exported_namespace="{SMARTOPS_NAMESPACE}"
              }[2m]
            )
          )
        )
        """
    )

    errors = query_prometheus(
        f"""
        sum(
          rate(
            nginx_ingress_controller_requests{
              host="{ODOO_INGRESS_HOST}",
              exported_namespace="{SMARTOPS_NAMESPACE}",
              status=~"5.."
            }[1m]
          )
        )
        """
    )

    logger.info(
        "ERP KPI check: p95_latency=%.3f 5xx_rate=%.3f",
        latency, errors
    )

    return latency < ERP_P95_LATENCY_OK and errors < ERP_5XX_RATE_OK


async def verify_deployment_rollout(
    request: DeploymentVerificationRequest,
) -> DeploymentVerificationResult:
    """
    Rollout + optional ERP KPI verification.
    """

    ns = request.namespace or k8s_core.DEFAULT_NAMESPACE

    with tracer.start_as_current_span("smartops.verify_deployment") as span:
        span.set_attribute("smartops.namespace", ns)
        span.set_attribute("smartops.deployment", request.deployment)

        try:
            initial_status = k8s_core.get_deployment_status(
                name=request.deployment,
                namespace=ns,
            )
        except Exception as exc:
            span.record_exception(exc)
            return DeploymentVerificationResult(
                status=VerificationStatus.FAILED,
                message=f"Failed to read deployment status: {exc}",
                namespace=ns,
                deployment=request.deployment,
            )

        desired = (
            request.expected_replicas
            if request.expected_replicas is not None
            else initial_status.get("replicas", 0)
        )

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

        last = rollout_result.get("last_observed", {}) or {}
        ready = last.get("ready_replicas", 0)
        available = last.get("available_replicas", 0)

        if rollout_result["status"] == "success":
            # -------------------------------
            # ERP KPI verification (Odoo only)
            # -------------------------------
            if request.deployment == "odoo-web":
                kpi_ok = verify_erp_kpis()
                span.set_attribute("smartops.verification.kpi_ok", kpi_ok)

                if not kpi_ok:
                    return DeploymentVerificationResult(
                        status=VerificationStatus.FAILED,
                        message="Deployment rolled out but ERP KPIs did not recover.",
                        namespace=ns,
                        deployment=request.deployment,
                        desired_replicas=desired,
                        ready_replicas=ready,
                        available_replicas=available,
                        details=last,
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

        if rollout_result["status"] == "timeout":
            return DeploymentVerificationResult(
                status=VerificationStatus.TIMED_OUT,
                message="Timed out waiting for deployment rollout.",
                namespace=ns,
                deployment=request.deployment,
                desired_replicas=desired,
                ready_replicas=ready,
                available_replicas=available,
                details=last,
            )

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


