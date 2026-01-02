"""
Simple prefix-based deployment name resolver for SmartOps.

Converts friendly names:
    erp-simulator       → smartops-erp-simulator
    orchestrator        → smartops-orchestrator
    grafana             → smartops-grafana

If the name already starts with 'smartops-', it is returned unchanged.

Optional: validate the resolved deployment name using K8s API.
"""

import logging
from typing import Optional

from kubernetes.client import ApiException

from ..utils.k8s_client import get_k8s_clients

logger = logging.getLogger("smartops.name_resolver")

SMARTOPS_PREFIX = "smartops-"


def resolve_deployment_name(name: str) -> str:
    """
    Convert a friendly name to the real Kubernetes Deployment name.

    Example:
        "erp-simulator"  -> "smartops-erp-simulator"
        "smartops-erp-simulator" -> unchanged
    """
    if name.startswith(SMARTOPS_PREFIX):
        return name

    resolved = SMARTOPS_PREFIX + name
    return resolved


def validate_deployment_exists(name: str, namespace: str) -> bool:
    """
    Optional helper to validate if a deployment actually exists in the cluster.
    Returns True if found, False otherwise.
    """
    _, apps_v1 = get_k8s_clients()
    try:
        apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
        return True
    except ApiException as exc:
        if exc.status == 404:
            return False
        logger.error("K8s API error while validating deployment=%s: %s", name, exc)
        return False


def resolve_and_validate(name: str, namespace: str) -> Optional[str]:
    """
    Resolve + validate. Returns:
        resolved name → if exists
        None          → if not found in cluster
    """
    resolved = resolve_deployment_name(name)
    if validate_deployment_exists(resolved, namespace):
        return resolved

    logger.warning(
        "resolve_and_validate: Deployment '%s' (resolved='%s') not found in namespace=%s",
        name,
        resolved,
        namespace,
    )
    return None
