import os
import requests
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class PrometheusClient:
    """
    Prometheus client for SmartOps Dashboard (progressive enhancement).

    Goals:
    - Never break the UI (Local Mode returns safe dummy values)
    - Prefer Kubernetes-native metrics (kube-state-metrics) as primary truth
    - Use duration histogram metrics *if they exist* (optional latency)
    """

    def __init__(self):
        # In K8s, prefer the in-cluster Service DNS.
        # In local dev, you normally port-forward Prometheus and set PROMETHEUS_URL=http://127.0.0.1:9090
        default_k8s_url = "http://smartops-prometheus-prometheus.smartops-dev:9090"
        default_local_url = "http://127.0.0.1:9090"

        self.enabled = bool(os.environ.get("KUBERNETES_SERVICE_HOST"))

        self.base_url = os.environ.get(
            "PROMETHEUS_URL",
            default_k8s_url if self.enabled else default_local_url
        )

        logger.info(f"PrometheusClient base_url={self.base_url} enabled={self.enabled}")

    # -------------------------------
    # Low-level helpers
    # -------------------------------

    def _instant_query(self, query: str) -> Optional[float]:
        """
        Execute an instant query and return a scalar float if available.
        Returns None if query fails or no result.
        """
        if not self.enabled:
            return None

        try:
            r = requests.get(
                f"{self.base_url}/api/v1/query",
                params={"query": query},
                timeout=3,
            )
            r.raise_for_status()
            payload = r.json()

            if payload.get("status") != "success":
                return None

            result = payload.get("data", {}).get("result", [])
            if not result:
                return None

            # Prometheus returns [ <timestamp>, "<value>" ]
            return float(result[0]["value"][1])

        except Exception as e:
            logger.warning(f"Prometheus instant query failed. query={query} err={e}")
            return None

    def _safe_int(self, v: Optional[float]) -> int:
        return int(v) if v is not None else 0

    # -------------------------------
    # Kubernetes-native KPIs (Primary)
    # -------------------------------

    def get_deployment_health(
        self,
        namespace: str,
        deployment: str,
    ) -> Dict[str, Any]:
        """
        Uses kube-state-metrics to compute deployment health.

        Metrics (typical):
        - kube_deployment_spec_replicas
        - kube_deployment_status_replicas_ready
        - kube_deployment_status_replicas_available

        Returns a stable schema even if metrics are missing.
        """
        if not self.enabled:
            # Local Mode dummy (truthy + non-breaking)
            desired = 3
            ready = 3
            available = 3
            return {
                "namespace": namespace,
                "deployment": deployment,
                "replicas_desired": desired,
                "replicas_ready": ready,
                "replicas_available": available,
                "status": "healthy" if ready >= desired else "degraded",
                "source": "dummy_local",
            }

        sel = f'namespace="{namespace}",deployment="{deployment}"'

        desired_q = f"max(kube_deployment_spec_replicas{{{sel}}})"
        ready_q = f"max(kube_deployment_status_replicas_ready{{{sel}}})"
        avail_q = f"max(kube_deployment_status_replicas_available{{{sel}}})"

        desired = self._instant_query(desired_q)
        ready = self._instant_query(ready_q)
        available = self._instant_query(avail_q)

        desired_i = self._safe_int(desired)
        ready_i = self._safe_int(ready)
        avail_i = self._safe_int(available)

        status = "healthy" if (desired_i > 0 and ready_i >= desired_i) else "degraded"

        return {
            "namespace": namespace,
            "deployment": deployment,
            "replicas_desired": desired_i,
            "replicas_ready": ready_i,
            "replicas_available": avail_i,
            "status": status,
            "source": "kube_state_metrics",
        }

    # -------------------------------
    # Optional latency (Progressive)
    # -------------------------------

    def get_latency_p95_ms_progressive(self, selectors: Dict[str, str]) -> Optional[int]:
        """
        Tries to compute p95 latency from *any* known duration histogram buckets.
        If not found, returns None (UI shows N/A).

        You told:
        - http_requests_total does NOT exist
        - duration metrics exist (name contains "duration")

        So we try a small list of common histogram bucket metric names.
        """
        if not self.enabled:
            return 180  # dummy local value

        # Convert dict selectors into {k="v",...}
        sel = ",".join([f'{k}="{v}"' for k, v in selectors.items()]) if selectors else ""
        if sel:
            sel = "{" + sel + "}"

        candidate_bucket_metrics = [
            # common HTTP-style
            "http_request_duration_seconds_bucket",
            "http_server_duration_seconds_bucket",
            "http_duration_seconds_bucket",
            # common custom
            "request_duration_seconds_bucket",
            "requests_duration_seconds_bucket",
            # generic
            "duration_seconds_bucket",
        ]

        for metric in candidate_bucket_metrics:
            q = (
                f"histogram_quantile(0.95, "
                f"sum(rate({metric}{sel}[5m])) by (le)"
                f")"
            )
            val = self._instant_query(q)
            if val is not None and val > 0:
                # seconds -> ms
                return int(val * 1000)

        return None
