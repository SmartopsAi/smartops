import os
import requests
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: Optional[bool] = None) -> Optional[bool]:
    """
    Parse boolean env vars safely.
    Returns:
      - True/False if set and parseable
      - default if not set or not parseable
    Accepts: true/false/1/0/yes/no/on/off (case-insensitive)
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip().lower()
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    return default


class PrometheusClient:
    """
    Prometheus client for SmartOps Dashboard (progressive enhancement).

    Production goals:
    - Never break the UI (local mode returns safe dummy values)
    - Enable Prometheus queries only when explicitly enabled/configured:
        - PROMETHEUS_ENABLED=true, OR
        - PROMETHEUS_URL is explicitly provided (port-forward / dev)
    - Prefer kube-state-metrics for workload health
    - Provide ERP Pilot KPIs (Odoo) via a locked PromQL contract
    """

    def __init__(self):
        # In K8s, prefer the in-cluster Service DNS.
        default_k8s_url = "http://smartops-prometheus-prometheus.smartops-dev:9090"
        default_local_url = "http://127.0.0.1:9090"

        prom_url = os.environ.get("PROMETHEUS_URL")

        in_cluster = bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
        explicit_prom = bool(prom_url)

        # Respect explicit enable/disable flag when present.
        # If not present, only enable when PROMETHEUS_URL is explicitly provided.
        enabled_flag = _env_bool("PROMETHEUS_ENABLED", default=None)
        if enabled_flag is None:
            self.enabled = explicit_prom
        else:
            self.enabled = enabled_flag or explicit_prom  # URL implies usable even if flag mis-set

        # Base URL (used only if enabled, but we still set it)
        self.base_url = prom_url or (default_k8s_url if in_cluster else default_local_url)
        self.base_url = self.base_url.rstrip("/")
        self.odoo_host = os.environ.get("ODOO_INGRESS_HOST", "odoo.localhost")
        self.odoo_namespace = os.environ.get("SMARTOPS_NAMESPACE", "smartops-dev")

        logger.info("PrometheusClient base_url=%s enabled=%s", self.base_url, self.enabled)

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
            logger.warning("Prometheus instant query failed. query=%s err=%s", query, e)
            return None

    def _safe_int(self, v: Optional[float]) -> int:
        return int(v) if v is not None else 0

    def _safe_float(self, v: Optional[float]) -> float:
        return float(v) if v is not None else 0.0

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
                "replica_source": "dummy_fallback",
                "metrics_source": "dummy_fallback",
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
            "replica_source": "prometheus",
            "metrics_source": "prometheus",
        }

    # -------------------------------
    # ERP Pilot KPIs (Odoo via ingress-nginx)
    # -------------------------------

    def get_odoo_kpis(self) -> Dict[str, Any]:
        """
        Returns the locked Odoo KPI contract values.

        Filters:
          host="{self.odoo_host}"
          exported_namespace="{self.odoo_namespace}"

        KPIs:
          - request_rate_rps
          - error_5xx_rps
          - latency_p95_ms

        Always returns a stable schema (dummy values in local mode).
        """
        if not self.enabled:
            return {
                "profile": "odoo",
                "request_rate_rps": 0.0,
                "error_5xx_rps": 0.0,
                "latency_p95_ms": 180,
                "source": "dummy_local",
            }

        req_rate_q = f"""
        sum(
          rate(
            nginx_ingress_controller_requests{{
              host="{self.odoo_host}",
              exported_namespace="{self.odoo_namespace}"
            }}[1m]
          )
        )
        """

        err_5xx_q = f"""
        sum(
          rate(
            nginx_ingress_controller_requests{{
              host="{self.odoo_host}",
              exported_namespace="{self.odoo_namespace}",
              status=~"5.."
            }}[1m]
          )
        )
        """

        p95_latency_s_q = f"""
        histogram_quantile(
          0.95,
          sum by (le) (
            rate(
              nginx_ingress_controller_request_duration_seconds_bucket{{
                host="{self.odoo_host}",
                exported_namespace="{self.odoo_namespace}"
              }}[2m]
            )
          )
        )
        """

        req_rate = self._safe_float(self._instant_query(req_rate_q))
        err_5xx = self._safe_float(self._instant_query(err_5xx_q))
        p95_s = self._instant_query(p95_latency_s_q)
        p95_ms = int(p95_s * 1000) if (p95_s is not None and p95_s > 0) else 0

        return {
            "profile": "odoo",
            "request_rate_rps": req_rate,
            "error_5xx_rps": err_5xx,
            "latency_p95_ms": p95_ms,
            "source": "prometheus",
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
