"""
Kubernetes client helper for SmartOps Orchestrator.

- Prefers in-cluster configuration (ServiceAccount).
- Falls back to local kubeconfig (for dev/testing).
"""

from __future__ import annotations

import logging
from typing import Tuple

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

logger = logging.getLogger("smartops.orchestrator.k8s")


def get_k8s_clients() -> Tuple[client.CoreV1Api, client.AppsV1Api]:
    """
    Returns (core_v1, apps_v1) API clients.

    Order of config:
      1. In-cluster (for pods in the cluster)
      2. KUBECONFIG / ~/.kube/config (for local dev)
    """
    try:
        config.load_incluster_config()
        logger.info("Loaded in-cluster Kubernetes configuration")
    except ConfigException:
        logger.warning("In-cluster config not found, trying local kubeconfig")
        config.load_kube_config()
        logger.info("Loaded local kubeconfig")

    core_v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()
    return core_v1, apps_v1

