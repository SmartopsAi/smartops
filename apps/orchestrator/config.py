import os


class Settings:
    """
    Centralized orchestrator configuration.

    Backed by environment variables so we can tune behavior per environment
    (dev / stage / prod) without changing code.

    Existing fields:
      - K8S_NAMESPACE: default Kubernetes namespace for SmartOps workloads
      - LOG_LEVEL: orchestrator log level
      - OTel_Endpoint: OTEL OTLP endpoint for traces/metrics

    New fields (Guardrails Step 1):
      - ORCH_MIN_REPLICAS: lower bound for allowed replica counts
      - ORCH_MAX_REPLICAS: upper bound for allowed replica counts
      - ORCH_ENFORCE_REPLICA_GUARDRAILS: enable/disable replica guardrails
    """

    # ------------------------------------------------------------------
    # Base orchestrator settings
    # ------------------------------------------------------------------
    K8S_NAMESPACE: str = os.getenv("SMARTOPS_NAMESPACE", "smartops-dev")
    LOG_LEVEL: str = os.getenv("ORCH_LOG_LEVEL", "INFO")

    # Keep the original attribute name for backward compatibility
    OTel_Endpoint: str = os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "http://smartops-otelcol:4317",
    )

    # Optional alias with a more conventional name (non-breaking)
    @property
    def OTEL_ENDPOINT(self) -> str:
        return self.OTel_Endpoint

    # ------------------------------------------------------------------
    # Guardrails: global replica limits (Step 1)
    # ------------------------------------------------------------------
    # Minimum allowed replicas for any SCALE operation. Typically 1,
    # but can be set to 0 in some environments for complete scale-down.
    ORCH_MIN_REPLICAS: int = int(os.getenv("ORCH_MIN_REPLICAS", "1"))

    # Maximum allowed replicas for any SCALE operation. Protects the
    # cluster from runaway scaling (e.g., bad AI policy or bug).
    ORCH_MAX_REPLICAS: int = int(os.getenv("ORCH_MAX_REPLICAS", "10"))

    # Master switch to turn replica guardrails on/off without code changes.
    ORCH_ENFORCE_REPLICA_GUARDRAILS: bool = (
        os.getenv("ORCH_ENFORCE_REPLICA_GUARDRAILS", "true").lower()
        in ("1", "true", "yes", "y")
    )

    def __init__(self) -> None:
        # Safety: ensure max >= min at runtime. If misconfigured, we
        # clamp ORCH_MAX_REPLICAS to ORCH_MIN_REPLICAS to avoid crashes.
        if self.ORCH_MAX_REPLICAS < self.ORCH_MIN_REPLICAS:
            # Log message is handled by whoever configures logging;
            # we avoid importing logging here to keep config lightweight.
            self.ORCH_MAX_REPLICAS = self.ORCH_MIN_REPLICAS


settings = Settings()
