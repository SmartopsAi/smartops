import logging
import random
import time
from typing import Any, Callable, Dict, Optional

from opentelemetry import trace
from ..config import settings  # NEW: replica guardrails

logger = logging.getLogger("smartops.orchestrator.action_runner")
tracer = trace.get_tracer(__name__)


class ActionRunner:
    """
    Executes Kubernetes-related actions with:
      - retries
      - exponential backoff
      - optional dry-run
      - OpenTelemetry spans
      - **guardrails for replica limits (new)**

    This is intentionally generic so it can be used by:
      - /v1/k8s/* low-level APIs
      - /v1/actions/execute (policy/AI-driven)
      - closed-loop controller
    """

    def __init__(
        self,
        max_retries: int = 2,
        base_backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 5.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds

    # ----------------------------------------------------------------------
    # Guardrail: Replica Limit Enforcement (SCALE only)
    # ----------------------------------------------------------------------
    def _enforce_scale_guardrails(
        self,
        replicas: Optional[int],
        target: Optional[str],
    ) -> Optional[str]:
        """
        Validate replicas against global min/max.

        Returns:
            None if OK, else error message string.
        """
        if not settings.ORCH_ENFORCE_REPLICA_GUARDRAILS:
            return None

        if replicas is None:
            return None  # nothing to check

        if replicas < settings.ORCH_MIN_REPLICAS:
            return (
                f"Replica guardrail violated: requested {replicas} < "
                f"min={settings.ORCH_MIN_REPLICAS} for {target}"
            )

        if replicas > settings.ORCH_MAX_REPLICAS:
            return (
                f"Replica guardrail violated: requested {replicas} > "
                f"max={settings.ORCH_MAX_REPLICAS} for {target}"
            )

        return None

    # ----------------------------------------------------------------------
    # Exponential Backoff
    # ----------------------------------------------------------------------
    def _compute_backoff(self, attempt: int) -> float:
        base = min(self.max_backoff_seconds, self.base_backoff_seconds * (2 ** attempt))
        jitter = random.uniform(0, base * 0.2)
        return base + jitter

    # ----------------------------------------------------------------------
    # Main Runner
    # ----------------------------------------------------------------------
    def run(
        self,
        action_type: str,
        action_fn: Callable[..., Any],
        *,
        dry_run: bool = False,
        target: Optional[str] = None,
        reason: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Execute an action function with retries, tracing,
        and **replica guardrails** for SCALE.
        """
        span_name = f"orchestrator.action.{action_type}"
        start_time = time.time()

        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("smartops.action.type", action_type)
            if target:
                span.set_attribute("smartops.action.target", target)
            if reason:
                span.set_attribute("smartops.action.reason", reason)
            span.set_attribute("smartops.action.dry_run", dry_run)

            # --------------------------------------------------------------
            # Guardrail enforcement: SCALE only
            # --------------------------------------------------------------
            if action_type == "scale":
                replicas = kwargs.get("replicas")
                error = self._enforce_scale_guardrails(replicas, target)

                if error:
                    span.set_attribute("smartops.action.status", "guardrail_blocked")
                    logger.warning(
                        "Guardrail BLOCKED scale action: %s (target=%s)",
                        error,
                        target,
                    )
                    duration = time.time() - start_time
                    return {
                        "status": "failed",
                        "attempts": 0,
                        "duration_seconds": duration,
                        "result": None,
                        "error": error,
                    }

            # --------------------------------------------------------------
            # Dry Run Shortcut
            # --------------------------------------------------------------
            if dry_run:
                logger.info(
                    "Dry-run action requested: type=%s target=%s reason=%s kwargs=%s",
                    action_type,
                    target,
                    reason,
                    kwargs,
                )
                duration = time.time() - start_time
                span.set_attribute("smartops.action.status", "dry_run")

                return {
                    "status": "dry_run",
                    "attempts": 0,
                    "duration_seconds": duration,
                    "result": None,
                    "error": None,
                }

            # --------------------------------------------------------------
            # Execution with Retries
            # --------------------------------------------------------------
            last_error: Optional[Exception] = None
            attempts = 0

            for attempt in range(self.max_retries + 1):
                attempts = attempt + 1
                try:
                    logger.info(
                        "Executing action: type=%s target=%s attempt=%d/%d",
                        action_type,
                        target,
                        attempts,
                        self.max_retries + 1,
                    )

                    span.add_event("attempt_start", {"attempt": attempts})

                    result = action_fn(**kwargs)

                    duration = time.time() - start_time
                    logger.info(
                        "Action completed: type=%s target=%s status=success duration=%.2fs attempts=%d",
                        action_type,
                        target,
                        duration,
                        attempts,
                    )
                    span.set_attribute("smartops.action.status", "success")
                    span.set_attribute("smartops.action.attempts", attempts)

                    return {
                        "status": "success",
                        "attempts": attempts,
                        "duration_seconds": duration,
                        "result": result,
                        "error": None,
                    }

                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.exception(
                        "Action failed: type=%s target=%s attempt=%d/%d error=%s",
                        action_type,
                        target,
                        attempts,
                        self.max_retries + 1,
                        exc,
                    )
                    span.record_exception(exc)

                    if attempt >= self.max_retries:
                        break

                    backoff = self._compute_backoff(attempt)
                    logger.warning(
                        "Retrying action after backoff: type=%s target=%s backoff=%.2fs next_attempt=%d",
                        action_type,
                        target,
                        backoff,
                        attempts + 1,
                    )
                    time.sleep(backoff)

            # --------------------------------------------------------------
            # All attempts exhausted
            # --------------------------------------------------------------
            duration = time.time() - start_time
            error_str = str(last_error) if last_error else "Unknown error"
            span.set_attribute("smartops.action.status", "failed")
            span.set_attribute("smartops.action.attempts", attempts)

            return {
                "status": "failed",
                "attempts": attempts,
                "duration_seconds": duration,
                "result": None,
                "error": error_str,
            }
