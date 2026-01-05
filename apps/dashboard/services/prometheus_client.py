import os
import time
import requests
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class PrometheusClient:
    def __init__(self):
        # Default Prometheus URL in K8s (often prometheus-server or similar)
        # Allows override via env var
        self.base_url = os.environ.get("PROMETHEUS_URL", "http://prometheus-server")
        self.enabled = bool(os.environ.get("KUBERNETES_SERVICE_HOST"))

    def _query(self, query: str) -> float:
        """Helper to execute an instant query and return a single scalar value."""
        if not self.enabled:
            return 0.0

        try:
            response = requests.get(
                f"{self.base_url}/api/v1/query",
                params={'query': query},
                timeout=2
            )
            data = response.json()
            if data['status'] == 'success' and data['data']['result']:
                # Return the value from the first result
                return float(data['data']['result'][0]['value'][1])
        except Exception as e:
            logger.warning(f"Prometheus query failed: {query}. Error: {e}")
        
        return 0.0

    def get_service_metrics(self, service_name: str) -> Dict[str, float]:
        """
        Fetches KPIs for a specific service.
        Note: Adjust labels (app= vs service=) to match your specific Helm chart labels.
        """
        if not self.enabled:
            # Return dummy data for Local Mode so UI doesn't break
            return {
                "rps": 12.5,
                "error_rate": 0.02,
                "p95_latency": 0.150
            }

        # PromQL Queries (Standard RED Method)
        # 1. Request Rate (RPS)
        rps_query = f'sum(rate(http_requests_total{{service="{service_name}"}}[1m]))'
        
        # 2. Error Rate (% of 5xx errors)
        err_query = f'sum(rate(http_requests_total{{service="{service_name}", status=~"5.."}}[1m])) / sum(rate(http_requests_total{{service="{service_name}"}}[1m]))'
        
        # 3. P95 Latency
        lat_query = f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{service="{service_name}"}}[5m])) by (le))'

        return {
            "rps": self._query(rps_query),
            "error_rate": self._query(err_query),
            "p95_latency": self._query(lat_query)
        }