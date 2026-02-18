"""
Deployment name resolver for SmartOps.

Supports BOTH:
1. SmartOps-prefixed deployments (smartops-*)
2. Standalone Helm releases (e.g. odoo-web)

Resolution order:
  1. Exact name as provided
  2. smartops-<name>
"""

import logging
from typing import Optional

from kubernetes.client import ApiException

from ..utils.k8s_client import get_k8s_clients

logger = logging.getLogger("smartops.name_resolver")

SMARTOPS_PREFIX = "smartops-"


def deployment_exists(name: str, namespace: str) -> bool:
    """
    Check if a deployment exists in the given namespace.
    """
    _, apps_v1 = get_k8s_clients()
    try:
        apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
        return True
    except ApiException as exc:
        if exc.status == 404:
            return False
        logger.error(
            "K8s API error while checking deployment=%s namespace=%s: %s",
            name,
            namespace,
            exc,
        )
        return False


def resolve_deployment_name(name: str, namespace: str) -> Optional[str]:
    """
    Resolve a deployment name safely.

    Resolution order:
      1. Exact name
      2. smartops-<name>

    Returns resolved name if found, else None.
    """

    # 1️⃣ Exact name (standalone Helm releases like odoo-web)
    if deployment_exists(name, namespace):
        logger.info("Resolved deployment using exact name: %s", name)
        return name

    # 2️⃣ SmartOps-prefixed name
    prefixed = SMARTOPS_PREFIX + name
    if deployment_exists(prefixed, namespace):
        logger.info("Resolved deployment using prefixed name: %s", prefixed)
        return prefixed

    logger.warning(
        "Deployment resolution failed: name='%s' namespace='%s'", name, namespace
    )
    return None
