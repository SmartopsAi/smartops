import os
import requests
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class OrchestratorClient:
    """
    Client used by the Dashboard to talk to the SmartOps Orchestrator.

    This client is intentionally thin:
    - No business logic
    - No retries / policies
    - Just correct API wiring
    """

    def __init__(self):
        # Determine base URL based on environment
        if os.environ.get("KUBERNETES_SERVICE_HOST"):
            # Running inside Kubernetes
            self.base_url = "http://smartops-orchestrator:8000"
        else:
            # Local development
            self.base_url = "http://localhost:8000"

        logger.info(f"OrchestratorClient initialized with base URL: {self.base_url}")

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Safe POST wrapper with clear error semantics.
        """
        url = f"{self.base_url}{endpoint}"

        try:
            resp = requests.post(url, json=payload, timeout=5)
            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.ConnectionError:
            logger.error(f"Failed to connect to Orchestrator at {url}")
            return {
                "status": "error",
                "message": "Orchestrator unreachable (is it running?)"
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Orchestrator API error: {e}")
            return {
                "status": "error",
                "message": str(e)
            }

    def _get(self, endpoint: str) -> Dict[str, Any]:
        """
        Safe GET wrapper.
        """
        url = f"{self.base_url}{endpoint}"

        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            return resp.json()

        except requests.exceptions.ConnectionError:
            logger.error(f"Failed to connect to Orchestrator at {url}")
            return {
                "status": "error",
                "message": "Orchestrator unreachable (is it running?)"
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"Orchestrator API error: {e}")
            return {
                "status": "error",
                "message": str(e)
            }

    # ------------------------------------------------------------------
    # Public API used by Dashboard
    # ------------------------------------------------------------------

    def trigger_scale(
        self,
        namespace: str,
        name: str,
        replicas: int,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """
        Trigger a Kubernetes Deployment scale action.

        Maps to:
        POST /v1/k8s/scale/{deployment_name}
        """
        payload = {
            "namespace": namespace,
            "replicas": replicas,
            "dry_run": dry_run,
        }

        return self._post(
            f"/v1/k8s/scale/{name}",
            payload
        )

    def trigger_restart(
        self,
        namespace: str,
        name: str,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """
        Trigger a Kubernetes Deployment restart.

        Maps to:
        POST /v1/k8s/restart/{deployment_name}
        """
        payload = {
            "namespace": namespace,
            "dry_run": dry_run,
        }

        return self._post(
            f"/v1/k8s/restart/{name}",
            payload
        )

    def verify_deployment(
        self,
        namespace: str,
        deployment: str,
        expected_replicas: int | None = None,
        timeout_seconds: int = 60,
        poll_interval_seconds: int = 5,
    ) -> Dict[str, Any]:
        """
        Verify a Kubernetes Deployment rollout.

        Maps to:
        POST /v1/verify/deployment
        """
        payload = {
            "namespace": namespace,
            "deployment": deployment,
            "expected_replicas": expected_replicas,
            "timeout_seconds": timeout_seconds,
            "poll_interval_seconds": poll_interval_seconds,
        }

        return self._post(
            "/v1/verify/deployment",
            payload
        )

    def get_action_history(self) -> list:
        """
        Fetch action execution history (if exposed by Orchestrator).

        Currently optional — dashboard will tolerate empty response.
        """
        result = self._get("/v1/actions/history")

        if isinstance(result, list):
            return result

        return []
