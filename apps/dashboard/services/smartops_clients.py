import os
import requests
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class OrchestratorClient:
    def __init__(self):
        # Determine base URL based on environment
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            # K8s Mode: Use the internal service DNS
            self.base_url = "http://smartops-orchestrator:8001"
        else:
            # Local Mode: Use localhost
            self.base_url = "http://localhost:8001"

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Helper for safe POST requests"""
        url = f"{self.base_url}{endpoint}"
        try:
            resp = requests.post(url, json=payload, timeout=5)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError:
            logger.error(f"Failed to connect to Orchestrator at {url}")
            return {"status": "error", "message": "Orchestrator unreachable (is it running?)"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Orchestrator API error: {e}")
            return {"status": "error", "message": str(e)}

    def trigger_scale(self, namespace: str, name: str, replicas: int, dry_run: bool = True) -> Dict[str, Any]:
        """Triggers a scaling action via the Orchestrator"""
        payload = {
            "namespace": namespace,
            "deployment_name": name,
            "replicas": replicas,
            "dry_run": dry_run
        }
        # Endpoint assumes apps/orchestrator/routers/k8s_router.py exposes /scale
        return self._post("/actions/scale", payload)

    def trigger_restart(self, namespace: str, name: str, dry_run: bool = True) -> Dict[str, Any]:
        """Triggers a rollout restart via the Orchestrator"""
        payload = {
            "namespace": namespace,
            "deployment_name": name,
            "dry_run": dry_run
        }
        return self._post("/actions/restart", payload)

    def get_action_history(self) -> list:
        """Fetches execution history (if Orchestrator exposes it)"""
        url = f"{self.base_url}/actions/history"
        try:
            resp = requests.get(url, timeout=3)
            if resp.status_code == 200:
                return resp.json()
            return []
        except Exception:
            return []