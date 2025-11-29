import logging
import os
import time
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from kubernetes.client import ApiException, AppsV1Api, CoreV1Api
from opentelemetry import trace
from prometheus_client import Counter, Histogram, Gauge

from ..utils.k8s_client import get_k8s_clients

logger = logging.getLogger("smartops.orchestrator.k8s")
tracer = trace.get_tracer(__name__)

# Default namespace → overridable via environment
DEFAULT_NAMESPACE = os.getenv("K8S_NAMESPACE", "smartops-dev")

# -------------------------------------------------------------------------
# Prometheus metrics for Kubernetes operations
# -------------------------------------------------------------------------

K8S_API_CALLS_TOTAL = Counter(
    "smartops_k8s_api_calls_total",
    "Total Kubernetes API calls from Orchestrator",
    ["verb", "resource", "namespace"],
)

K8S_API_ERRORS_TOTAL = Counter(
    "smartops_k8s_api_errors_total",
    "Total failed Kubernetes API calls from Orchestrator",
    ["verb", "resource", "namespace"],
)

K8S_API_LATENCY_SECONDS = Histogram(
    "smartops_k8s_api_latency_seconds",
    "Latency of Kubernetes API calls from Orchestrator",
    ["verb", "resource", "namespace"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)

K8S_SCALE_TOTAL = Counter(
    "smartops_k8s_scale_total",
    "Total Kubernetes Deployment scale operations",
    ["namespace", "deployment"],
)

K8S_RESTART_TOTAL = Counter(
    "smartops_k8s_restart_total",
    "Total Kubernetes Deployment restart operations",
    ["namespace", "deployment"],
)

K8S_PATCH_TOTAL = Counter(
    "smartops_k8s_patch_total",
    "Total Kubernetes Deployment patch operations",
    ["namespace", "deployment"],
)

DEPLOYMENT_DESIRED_REPLICAS = Gauge(
    "smartops_k8s_deployment_desired_replicas",
    "Desired replicas per Deployment (last observed)",
    ["namespace", "deployment"],
)

DEPLOYMENT_READY_REPLICAS = Gauge(
    "smartops_k8s_deployment_ready_replicas",
    "Ready replicas per Deployment (last observed)",
    ["namespace", "deployment"],
)


# -------------------------------------------------------------------------
# Internal helpers
# -------------------------------------------------------------------------


def _resolve_namespace(namespace: Optional[str]) -> str:
    """Use provided namespace or fall back to DEFAULT_NAMESPACE."""
    return namespace or DEFAULT_NAMESPACE


def _clients() -> Tuple[CoreV1Api, AppsV1Api]:
    """
    Get CoreV1 and AppsV1 API clients from a unified source.
    This ensures:
    - in-cluster vs local dev automatically handled,
    - correct DI pattern,
    - compatible with testing mocks.
    """
    core_v1, apps_v1 = get_k8s_clients()
    return core_v1, apps_v1


# -------------------------------------------------------------------------
# Pod Operations
# -------------------------------------------------------------------------


def list_pods(
    namespace: Optional[str] = None,
    label_selector: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Returns a list of pods with basic metadata for SmartOps usage.
    """
    ns = _resolve_namespace(namespace)
    labels = {"verb": "list", "resource": "pod", "namespace": ns}

    with tracer.start_as_current_span("k8s.list_pods") as span:
        span.set_attribute("smartops.k8s.namespace", ns)
        if label_selector:
            span.set_attribute("smartops.k8s.label_selector", label_selector)

        core_v1, _ = _clients()

        start = time.time()
        try:
            resp = core_v1.list_namespaced_pod(
                namespace=ns,
                label_selector=label_selector or "",
            )
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
        except ApiException as exc:
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
            K8S_API_ERRORS_TOTAL.labels(**labels).inc()
            logger.error("Error listing pods in %s: %s", ns, exc)
            span.record_exception(exc)
            raise

        result: List[Dict[str, Any]] = []
        for pod in resp.items:
            result.append(
                {
                    "name": pod.metadata.name,
                    "namespace": pod.metadata.namespace,
                    "phase": pod.status.phase,
                    "pod_ip": pod.status.pod_ip,
                    "host_ip": pod.status.host_ip,
                    "labels": pod.metadata.labels or {},
                    "containers": [
                        {"name": c.name, "image": c.image}
                        for c in (pod.spec.containers or [])
                    ],
                }
            )

        span.set_attribute("smartops.k8s.pod_count", len(result))
        return result


def delete_pod(
    name: str,
    namespace: Optional[str] = None,
    grace_period_seconds: int = 30,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Delete a pod — used for:
    • targeted restarts
    • chaos injection
    • stale pod cleanup
    """
    ns = _resolve_namespace(namespace)
    labels = {"verb": "delete", "resource": "pod", "namespace": ns}

    with tracer.start_as_current_span("k8s.delete_pod") as span:
        span.set_attribute("smartops.k8s.pod", name)
        span.set_attribute("smartops.k8s.namespace", ns)
        span.set_attribute("smartops.k8s.dry_run", dry_run)

        core_v1, _ = _clients()

        body = {"gracePeriodSeconds": grace_period_seconds}
        dry = "All" if dry_run else None

        start = time.time()
        try:
            resp = core_v1.delete_namespaced_pod(
                name=name,
                namespace=ns,
                body=body,
                dry_run=dry,
            )
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
        except ApiException as exc:
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
            K8S_API_ERRORS_TOTAL.labels(**labels).inc()
            logger.error("Error deleting pod %s/%s: %s", ns, name, exc)
            span.record_exception(exc)
            raise

        return {
            "name": name,
            "namespace": ns,
            "dry_run": dry_run,
            "grace_period_seconds": grace_period_seconds,
            "status": getattr(resp, "status", None),
        }


# -------------------------------------------------------------------------
# Deployment listing & status
# -------------------------------------------------------------------------


def list_deployments(
    namespace: Optional[str] = None,
    label_selector: Optional[str] = None,
) -> List[Dict[str, Any]]:
    ns = _resolve_namespace(namespace)
    labels = {"verb": "list", "resource": "deployment", "namespace": ns}

    with tracer.start_as_current_span("k8s.list_deployments") as span:
        span.set_attribute("smartops.k8s.namespace", ns)
        if label_selector:
            span.set_attribute("smartops.k8s.label_selector", label_selector)

        _, apps_v1 = _clients()

        start = time.time()
        try:
            resp = apps_v1.list_namespaced_deployment(
                namespace=ns,
                label_selector=label_selector or "",
            )
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
        except ApiException as exc:
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
            K8S_API_ERRORS_TOTAL.labels(**labels).inc()
            logger.error("Error listing deployments in %s: %s", ns, exc)
            span.record_exception(exc)
            raise

        output: List[Dict[str, Any]] = []
        for dep in resp.items:
            status = dep.status
            spec = dep.spec
            name = dep.metadata.name
            ready = status.ready_replicas or 0
            desired = spec.replicas or 0

            DEPLOYMENT_DESIRED_REPLICAS.labels(
                namespace=ns, deployment=name
            ).set(desired)
            DEPLOYMENT_READY_REPLICAS.labels(
                namespace=ns, deployment=name
            ).set(ready)

            output.append(
                {
                    "name": name,
                    "namespace": dep.metadata.namespace,
                    "replicas": spec.replicas,
                    "ready_replicas": status.ready_replicas,
                    "available_replicas": status.available_replicas,
                    "updated_replicas": status.updated_replicas,
                    "labels": dep.metadata.labels or {},
                }
            )

        span.set_attribute("smartops.k8s.deployment_count", len(output))
        return output


def get_deployment_status(
    name: str,
    namespace: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Gives full deployment status in a consistent schema.
    Useful for:
    - verification_service
    - dashboards
    - closed-loop evaluation
    """
    ns = _resolve_namespace(namespace)
    labels = {"verb": "read", "resource": "deployment", "namespace": ns}

    with tracer.start_as_current_span("k8s.get_deployment_status") as span:
        span.set_attribute("smartops.k8s.deployment", name)
        span.set_attribute("smartops.k8s.namespace", ns)

        _, apps_v1 = _clients()

        start = time.time()
        try:
            dep = apps_v1.read_namespaced_deployment(name=name, namespace=ns)
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
        except ApiException as exc:
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
            K8S_API_ERRORS_TOTAL.labels(**labels).inc()
            logger.error("Error getting deployment status %s/%s: %s", ns, name, exc)
            span.record_exception(exc)
            raise

        status = dep.status
        spec = dep.spec

        desired = spec.replicas or 0
        ready = status.ready_replicas or 0

        DEPLOYMENT_DESIRED_REPLICAS.labels(
            namespace=ns, deployment=name
        ).set(desired)
        DEPLOYMENT_READY_REPLICAS.labels(
            namespace=ns, deployment=name
        ).set(ready)

        return {
            "name": dep.metadata.name,
            "namespace": dep.metadata.namespace,
            "replicas": spec.replicas,
            "ready_replicas": status.ready_replicas,
            "updated_replicas": status.updated_replicas,
            "available_replicas": status.available_replicas,
            "generation": dep.metadata.generation,
            "observed_generation": status.observed_generation,
            "conditions": [
                {
                    "type": c.type,
                    "status": c.status,
                    "reason": c.reason,
                    "message": c.message,
                    "last_update_time": getattr(c, "last_update_time", None),
                }
                for c in (status.conditions or [])
            ],
        }


# -------------------------------------------------------------------------
# Deployment scale / restart / patch
# -------------------------------------------------------------------------


def scale_deployment(
    name: str,
    replicas: int,
    namespace: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    ns = _resolve_namespace(namespace)
    labels = {"verb": "patch_scale", "resource": "deployment", "namespace": ns}

    with tracer.start_as_current_span("k8s.scale_deployment") as span:
        span.set_attribute("smartops.k8s.deployment", name)
        span.set_attribute("smartops.k8s.replicas", replicas)
        span.set_attribute("smartops.k8s.namespace", ns)
        span.set_attribute("smartops.k8s.dry_run", dry_run)

        _, apps_v1 = _clients()
        body = {"spec": {"replicas": replicas}}

        dry = "All" if dry_run else None

        start = time.time()
        try:
            resp = apps_v1.patch_namespaced_deployment_scale(
                name=name,
                namespace=ns,
                body=body,
                dry_run=dry,
            )
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)

            K8S_SCALE_TOTAL.labels(namespace=ns, deployment=name).inc()

            desired = resp.spec.replicas or 0
            DEPLOYMENT_DESIRED_REPLICAS.labels(
                namespace=ns, deployment=name
            ).set(desired)
        except ApiException as exc:
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
            K8S_API_ERRORS_TOTAL.labels(**labels).inc()
            logger.error("Error scaling deployment %s/%s: %s", ns, name, exc)
            span.record_exception(exc)
            raise

        return {
            "name": resp.metadata.name,
            "namespace": ns,
            "replicas": resp.spec.replicas,
            "dry_run": dry_run,
        }


def restart_deployment(
    name: str,
    namespace: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Equivalent to: `kubectl rollout restart`
    Implemented by bumping pod-template annotation.
    """
    ns = _resolve_namespace(namespace)
    labels = {"verb": "patch_restart", "resource": "deployment", "namespace": ns}

    with tracer.start_as_current_span("k8s.restart_deployment") as span:
        span.set_attribute("smartops.k8s.deployment", name)
        span.set_attribute("smartops.k8s.namespace", ns)
        span.set_attribute("smartops.k8s.dry_run", dry_run)

        _, apps_v1 = _clients()
        now = datetime.now(timezone.utc).isoformat()

        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now
                        }
                    }
                }
            }
        }

        dry = "All" if dry_run else None

        start = time.time()
        try:
            apps_v1.patch_namespaced_deployment(
                name=name,
                namespace=ns,
                body=body,
                dry_run=dry,
            )
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)

            K8S_RESTART_TOTAL.labels(namespace=ns, deployment=name).inc()
        except ApiException as exc:
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
            K8S_API_ERRORS_TOTAL.labels(**labels).inc()
            logger.error("Error restarting deployment %s/%s: %s", ns, name, exc)
            span.record_exception(exc)
            raise

        return {
            "name": name,
            "namespace": ns,
            "restarted_at": now,
            "dry_run": dry_run,
        }


def patch_deployment(
    name: str,
    patch_body: Dict[str, Any],
    namespace: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Generic PATCH action for deployments.
    THIS IS POWERFUL — SmartOps Policy Engine will eventually
    enforce guardrails to restrict allowable patch fields.
    """
    ns = _resolve_namespace(namespace)
    labels = {"verb": "patch", "resource": "deployment", "namespace": ns}

    with tracer.start_as_current_span("k8s.patch_deployment") as span:
        span.set_attribute("smartops.k8s.deployment", name)
        span.set_attribute("smartops.k8s.namespace", ns)
        span.set_attribute("smartops.k8s.dry_run", dry_run)

        _, apps_v1 = _clients()
        dry = "All" if dry_run else None

        start = time.time()
        try:
            apps_v1.patch_namespaced_deployment(
                name=name,
                namespace=ns,
                body=patch_body,
                dry_run=dry,
            )
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)

            K8S_PATCH_TOTAL.labels(namespace=ns, deployment=name).inc()
        except ApiException as exc:
            duration = time.time() - start
            K8S_API_CALLS_TOTAL.labels(**labels).inc()
            K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
            K8S_API_ERRORS_TOTAL.labels(**labels).inc()
            logger.error("Error patching deployment %s/%s: %s", ns, name, exc)
            span.record_exception(exc)
            raise

        return {"name": name, "namespace": ns, "dry_run": dry_run}


# -------------------------------------------------------------------------
# Deployment rollout verification helpers
# -------------------------------------------------------------------------


def wait_for_deployment_rollout(
    name: str,
    namespace: Optional[str] = None,
    timeout_seconds: int = 60,
    poll_interval_seconds: int = 5,
) -> Dict[str, Any]:
    """
    Wait for rollout completion:
    - observed_generation ≥ generation
    - updated_replicas ≥ desired
    - ready_replicas ≥ desired
    - available_replicas ≥ desired

    Returns:
        {
          "status": "success" | "timeout",
          "last_observed": {
              "replicas": int,
              "updated_replicas": int,
              "ready_replicas": int,
              "available_replicas": int,
              "observed_generation": int,
              "generation": int,
          }
        }
    """

    ns = _resolve_namespace(namespace)
    labels = {"verb": "read", "resource": "deployment", "namespace": ns}

    with tracer.start_as_current_span("k8s.wait_for_deployment_rollout") as span:
        span.set_attribute("smartops.k8s.deployment", name)
        span.set_attribute("smartops.k8s.namespace", ns)
        span.set_attribute("smartops.k8s.timeout_seconds", timeout_seconds)
        span.set_attribute("smartops.k8s.poll_interval_seconds", poll_interval_seconds)

        _, apps_v1 = _clients()
        start = time.time()
        last_status: Optional[Dict[str, Any]] = None
        iteration = 0

        while True:
            iteration += 1
            loop_start = time.time()
            try:
                dep = apps_v1.read_namespaced_deployment(name=name, namespace=ns)
                duration = time.time() - loop_start
                K8S_API_CALLS_TOTAL.labels(**labels).inc()
                K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
            except ApiException as exc:
                duration = time.time() - loop_start
                K8S_API_CALLS_TOTAL.labels(**labels).inc()
                K8S_API_LATENCY_SECONDS.labels(**labels).observe(duration)
                K8S_API_ERRORS_TOTAL.labels(**labels).inc()
                logger.error("Error waiting for rollout %s/%s: %s", ns, name, exc)
                span.record_exception(exc)
                raise

            status = dep.status
            spec = dep.spec

            desired = spec.replicas or 0
            updated = status.updated_replicas or 0
            ready = status.ready_replicas or 0
            available = status.available_replicas or 0

            DEPLOYMENT_DESIRED_REPLICAS.labels(
                namespace=ns, deployment=name
            ).set(desired)
            DEPLOYMENT_READY_REPLICAS.labels(
                namespace=ns, deployment=name
            ).set(ready)

            last_status = {
                "replicas": desired,
                "updated_replicas": updated,
                "ready_replicas": ready,
                "available_replicas": available,
                "observed_generation": status.observed_generation,
                "generation": dep.metadata.generation,
            }

            logger.debug(
                "Rollout status %s/%s [iter=%d]: %s",
                ns,
                name,
                iteration,
                last_status,
            )

            span.add_event(
                "rollout_poll",
                {
                    "iteration": iteration,
                    "desired": desired,
                    "updated": updated,
                    "ready": ready,
                    "available": available,
                },
            )

            if (
                status.observed_generation is not None
                and dep.metadata.generation is not None
                and status.observed_generation >= dep.metadata.generation
                and updated >= desired
                and ready >= desired
                and available >= desired
            ):
                span.set_attribute("smartops.k8s.rollout_status", "success")
                return {"status": "success", "last_observed": last_status}

            elapsed = time.time() - start
            if elapsed > timeout_seconds:
                logger.warning(
                    "Timeout waiting for rollout of %s/%s after %.2fs",
                    ns,
                    name,
                    elapsed,
                )
                span.set_attribute("smartops.k8s.rollout_status", "timeout")
                return {"status": "timeout", "last_observed": last_status}

            # Small jitter to avoid thundering herd / synchronized polling
            jitter = random.uniform(0, poll_interval_seconds * 0.2)
            sleep_for = poll_interval_seconds + jitter
            time.sleep(sleep_for)
