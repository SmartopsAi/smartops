import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional, Union, Dict, Tuple, List

from opentelemetry import trace
from prometheus_client import Counter, Histogram, Gauge

from ..models.signal_models import AnomalySignal, RcaSignal, AnomalyType
from ..models.action_models import (
    ActionRequest,
    ActionType,
    K8sTarget,
    ScaleParams,
)
from ..models.verification_models import VerificationStatus
from ..services.k8s_core import DEFAULT_NAMESPACE, list_deployments
from ..services import orchestrator_service  # use execute_action()
from ..utils.name_resolver import resolve_deployment_name

logger = logging.getLogger("smartops.closed_loop")
tracer = trace.get_tracer(__name__)

# --------------------------------------------------------------------------
# Prometheus metrics (Prometheus Python client)
# --------------------------------------------------------------------------

CLOSED_LOOP_SIGNALS_TOTAL = Counter(
    "orchestrator_closed_loop_signals_total",
    "Total number of signals processed by the closed-loop controller",
    ["kind", "result"],  # result: accepted | dropped_queue_full
)

CLOSED_LOOP_ACTIONS_TOTAL = Counter(
    "orchestrator_closed_loop_actions_total",
    "Total number of actions executed by the closed-loop controller",
    ["type", "status", "verification_status"],  # status: success|failed|exception
)

CLOSED_LOOP_RETRIES_TOTAL = Counter(
    "orchestrator_closed_loop_retries_total",
    "Total number of retries scheduled by the closed-loop controller",
    ["type"],
)

CLOSED_LOOP_DURATION_SECONDS = Histogram(
    "orchestrator_closed_loop_duration_seconds",
    "End-to-end closed-loop latency from signal enqueue to terminal outcome",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
)

CLOSED_LOOP_ACTION_DURATION_SECONDS = Histogram(
    "orchestrator_closed_loop_action_duration_seconds",
    "Duration of orchestrator action+verification per closed-loop signal",
    buckets=(0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60),
)

CLOSED_LOOP_QUEUE_DEPTH = Gauge(
    "orchestrator_closed_loop_queue_depth",
    "Current depth of the closed-loop processing queue",
)

CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL = Counter(
    "orchestrator_closed_loop_guardrail_blocks_total",
    "Number of times closed-loop guardrails blocked an action before execution",
    ["type", "reason"],
)


@dataclass
class QueueItem:
    kind: str  # "anomaly" or "rca"
    signal: Union[AnomalySignal, RcaSignal]
    attempt: int = 0
    # Timestamp when the signal was first enqueued into the closed-loop queue
    enqueued_at: float = field(default_factory=time.time)


# ----------------------------------------------------------------------
# NEW: Guardrail detection helper (for orchestrator-level HTTP exceptions)
# ----------------------------------------------------------------------

def _is_guardrail_exception(exc: Exception) -> bool:
    """
    True if orchestrator blocked action due to replica guardrails.
    We detect:
      - fastapi.HTTPException with status_code == 400
      - message containing "guardrail"/"replica"
    """
    try:
        from fastapi import HTTPException
    except Exception:  # noqa: BLE001
        return False

    if not isinstance(exc, HTTPException):
        return False

    if exc.status_code != 400:
        return False

    msg = str(exc.detail).lower()
    return "guardrail" in msg or "replica" in msg


class ClosedLoopManager:
    """
    Closed-loop engine for SmartOps.

    Receives anomaly/RCA signals, maps them to actions, and dispatches them
    to the orchestrator with verification, applying cooldowns and retries.

    Metrics & Telemetry:
      - Prometheus counters/histograms for signals, actions, retries, queue depth
      - OTEL spans for each processed signal and action outcome
      - End-to-end closed-loop latency from enqueue → terminal outcome

    Guardrails (moderate profile by default):
      - Max replicas (GUARDRAIL_MAX_REPLICAS, default 8)
      - Max actions per hour per (namespace, deployment, type)
        (GUARDRAIL_MAX_ACTIONS_PER_HOUR, default 6)
      - Max net scale increase within 15 minutes per deployment
        (GUARDRAIL_MAX_SCALE_INCREASE_15M, default +3)
    """

    def __init__(
        self,
        cooldown_seconds: int = 300,
        max_retries: int = 2,
        base_backoff_seconds: int = 5,
    ) -> None:
        # Optional queue max size (0 = unbounded). If bounded, we drop when full.
        maxsize_env = int(os.getenv("CLOSED_LOOP_QUEUE_MAXSIZE", "0"))
        self.queue: "asyncio.Queue[QueueItem]" = asyncio.Queue(maxsize=maxsize_env)

        self.cooldown_seconds = cooldown_seconds
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds

        # Guardrail configuration (moderate profile by default)
        self.max_replicas: int = int(os.getenv("GUARDRAIL_MAX_REPLICAS", "8"))
        self.max_actions_per_hour: int = int(
            os.getenv("GUARDRAIL_MAX_ACTIONS_PER_HOUR", "6")
        )
        self.max_scale_increase_15m: int = int(
            os.getenv("GUARDRAIL_MAX_SCALE_INCREASE_15M", "3")
        )

        # (namespace, name, actionType) -> last_action_timestamp (cooldown)
        self._last_action_at: Dict[Tuple[str, str, str], float] = {}

        # (namespace, name, actionType) -> [timestamps] for per-hour rate limiting
        self._action_history: Dict[Tuple[str, str, str], List[float]] = {}

        # (namespace, name) -> [(timestamp, delta_replicas)] for scale-rate guardrail
        self._scale_history: Dict[Tuple[str, str], List[Tuple[float, int]]] = {}

        # Worker task (single consumer)
        self._worker_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._worker_task is None:
            logger.info("Starting ClosedLoopManager worker")
            CLOSED_LOOP_QUEUE_DEPTH.set(self.queue.qsize())
            self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        if self._worker_task:
            logger.info("Stopping ClosedLoopManager worker")
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None
            CLOSED_LOOP_QUEUE_DEPTH.set(self.queue.qsize())

    # ------------------------------------------------------------------
    # Public enqueue API
    # ------------------------------------------------------------------

    async def enqueue_anomaly(self, signal: AnomalySignal) -> None:
        item = QueueItem(kind="anomaly", signal=signal)
        try:
            self.queue.put_nowait(item)
            CLOSED_LOOP_SIGNALS_TOTAL.labels(kind="anomaly", result="accepted").inc()
        except asyncio.QueueFull:
            logger.warning(
                "ClosedLoopManager: queue full, dropping anomaly signal windowId=%s service=%s",
                signal.windowId,
                signal.service,
            )
            CLOSED_LOOP_SIGNALS_TOTAL.labels(
                kind="anomaly", result="dropped_queue_full"
            ).inc()
            return

        CLOSED_LOOP_QUEUE_DEPTH.set(self.queue.qsize())

    async def enqueue_rca(self, signal: RcaSignal) -> None:
        item = QueueItem(kind="rca", signal=signal)
        try:
            self.queue.put_nowait(item)
            CLOSED_LOOP_SIGNALS_TOTAL.labels(kind="rca", result="accepted").inc()
        except asyncio.QueueFull:
            logger.warning(
                "ClosedLoopManager: queue full, dropping RCA signal windowId=%s service=%s",
                signal.windowId,
                signal.service or "",
            )
            CLOSED_LOOP_SIGNALS_TOTAL.labels(
                kind="rca", result="dropped_queue_full"
            ).inc()
            return

        CLOSED_LOOP_QUEUE_DEPTH.set(self.queue.qsize())

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    async def _worker(self) -> None:
        while True:
            CLOSED_LOOP_QUEUE_DEPTH.set(self.queue.qsize())

            item: QueueItem = await self.queue.get()
            try:
                await self._process_item(item)
            except Exception:  # noqa: BLE001
                logger.exception("ClosedLoopManager: unhandled error while processing item")
            finally:
                total_duration = time.time() - item.enqueued_at
                CLOSED_LOOP_DURATION_SECONDS.observe(total_duration)

                self.queue.task_done()
                CLOSED_LOOP_QUEUE_DEPTH.set(self.queue.qsize())

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    async def _process_item(self, item: QueueItem) -> None:
        with tracer.start_as_current_span("smartops.closed_loop.process_signal") as span:
            span.set_attribute("smartops.signal.kind", item.kind)
            span.set_attribute("smartops.signal.attempt", item.attempt)

            # ------------------------------------------------------------------
            # 1) Map signal → ActionRequest
            # ------------------------------------------------------------------
            if item.kind == "anomaly":
                signal: AnomalySignal = item.signal  # type: ignore
                span.set_attribute("smartops.signal.windowId", signal.windowId)
                span.set_attribute("smartops.signal.service", signal.service)
                span.set_attribute("smartops.signal.type", signal.type.value)
                span.set_attribute("smartops.signal.score", signal.score)
                action_req = await self._map_anomaly_to_action(signal)
            else:
                signal = item.signal  # type: ignore
                span.set_attribute("smartops.signal.windowId", signal.windowId)
                span.set_attribute("smartops.signal.service", signal.service or "")
                span.set_attribute("smartops.signal.confidence", signal.confidence)
                if signal.rankedCauses:
                    primary = signal.rankedCauses[0]
                    span.set_attribute("smartops.signal.primary_cause", primary.cause)
                    span.set_attribute("smartops.signal.primary_svc", primary.svc)
                    span.set_attribute("smartops.signal.primary_probability", primary.probability)
                action_req = await self._map_rca_to_action(signal)

            if action_req is None:
                logger.info("ClosedLoopManager: no remediation action derived for signal %s", item)
                span.set_attribute("smartops.closed_loop.action_derived", False)
                return

            span.set_attribute("smartops.closed_loop.action_derived", True)
            span.set_attribute("smartops.target.namespace", action_req.target.namespace)
            span.set_attribute("smartops.target.name", action_req.target.name)
            span.set_attribute("smartops.action.type", action_req.type.value)
            if action_req.reason:
                span.set_attribute("smartops.action.reason", action_req.reason)

            key = (
                action_req.target.namespace,
                action_req.target.name,
                action_req.type.value,
            )
            ns = action_req.target.namespace
            deployment_name = action_req.target.name

            now = time.time()

            # ------------------------------------------------------------------
            # 2) Cooldown check
            # ------------------------------------------------------------------
            last = self._last_action_at.get(key)
            if last is not None:
                elapsed = now - last
                cooldown_remaining = self.cooldown_seconds - elapsed
                span.set_attribute("smartops.closed_loop.cooldown_elapsed_seconds", elapsed)
                span.set_attribute(
                    "smartops.closed_loop.cooldown_remaining_seconds",
                    max(0.0, cooldown_remaining),
                )

                if elapsed < self.cooldown_seconds:
                    logger.info(
                        "ClosedLoopManager: cooldown active for %s (remaining=%.1fs), skipping action",
                        key,
                        cooldown_remaining,
                    )
                    span.set_attribute("smartops.closed_loop.cooldown_skipped", True)
                    return

            span.set_attribute("smartops.closed_loop.cooldown_skipped", False)

            # ------------------------------------------------------------------
            # 2b) NEW – Per-hour rate guardrail & scale-specific guardrails
            # ------------------------------------------------------------------
            action_type_label = action_req.type.value

            # Per-hour max actions per (ns, deployment, type)
            if self.max_actions_per_hour > 0:
                hist_key = key
                history = self._action_history.get(hist_key, [])
                cutoff = now - 3600
                history = [t for t in history if t >= cutoff]
                self._action_history[hist_key] = history

                if len(history) >= self.max_actions_per_hour:
                    reason = "max_actions_per_hour_exceeded"
                    logger.warning(
                        "ClosedLoopManager: guardrail %s for %s, skipping action",
                        reason,
                        hist_key,
                    )
                    span.set_attribute("smartops.closed_loop.guardrail.blocked", True)
                    span.set_attribute("smartops.closed_loop.guardrail.reason", reason)
                    CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL.labels(
                        type=action_type_label,
                        reason=reason,
                    ).inc()
                    return

            # Scale-specific guardrails
            if action_req.type == ActionType.SCALE and action_req.scale is not None:
                # Get current replicas to compute delta
                current = self._get_current_replicas(ns, deployment_name)
                if current is None:
                    logger.warning(
                        "ClosedLoopManager: cannot read current replicas for %s/%s in guardrail check",
                        ns,
                        deployment_name,
                    )
                else:
                    desired = action_req.scale.replicas
                    delta = desired - current

                    # Absolute max replicas
                    if self.max_replicas > 0 and desired > self.max_replicas:
                        reason = "max_replicas_exceeded"
                        logger.warning(
                            "ClosedLoopManager: guardrail %s for %s/%s (desired=%d, limit=%d), skipping action",
                            reason,
                            ns,
                            deployment_name,
                            desired,
                            self.max_replicas,
                        )
                        span.set_attribute("smartops.closed_loop.guardrail.blocked", True)
                        span.set_attribute("smartops.closed_loop.guardrail.reason", reason)
                        CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL.labels(
                            type=action_type_label,
                            reason=reason,
                        ).inc()
                        return

                    # Scale rate limit within 15 minutes
                    if delta > 0 and self.max_scale_increase_15m > 0:
                        sh_key = (ns, deployment_name)
                        shistory = self._scale_history.get(sh_key, [])
                        cutoff_15m = now - 900
                        shistory = [(t, d) for (t, d) in shistory if t >= cutoff_15m]
                        net_recent_inc = sum(max(0, d) for (_, d) in shistory)

                        if net_recent_inc + delta > self.max_scale_increase_15m:
                            reason = "max_scale_increase_15m_exceeded"
                            logger.warning(
                                "ClosedLoopManager: guardrail %s for %s/%s "
                                "(recent_inc=%d, delta=%d, limit=%d), skipping action",
                                reason,
                                ns,
                                deployment_name,
                                net_recent_inc,
                                delta,
                                self.max_scale_increase_15m,
                            )
                            span.set_attribute("smartops.closed_loop.guardrail.blocked", True)
                            span.set_attribute("smartops.closed_loop.guardrail.reason", reason)
                            CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL.labels(
                                type=action_type_label,
                                reason=reason,
                            ).inc()
                            return

                        # Record this positive scale delta into history
                        shistory.append((now, delta))
                        self._scale_history[sh_key] = shistory

            # No guardrail block → record in history and continue
            if self.max_actions_per_hour > 0:
                hist_key2 = key
                history2 = self._action_history.get(hist_key2, [])
                history2.append(now)
                self._action_history[hist_key2] = history2

            span.set_attribute("smartops.closed_loop.guardrail.blocked", False)

            # ------------------------------------------------------------------
            # 3) Execute via orchestrator
            # ------------------------------------------------------------------
            verification_status_label = "NONE"

            try:
                logger.info(
                    "ClosedLoopManager: executing %s on %s/%s (attempt=%d)",
                    action_req.type.value,
                    action_req.target.namespace,
                    action_req.target.name,
                    item.attempt,
                )
                start_action = time.time()

                result = await orchestrator_service.execute_action(action_req)

                action_duration = time.time() - start_action
                CLOSED_LOOP_ACTION_DURATION_SECONDS.observe(action_duration)

                span.set_attribute("smartops.action.duration_sec", action_duration)
                span.set_attribute("smartops.action.success", result.success)

                verification = result.verification
                if verification:
                    verification_status_label = verification.status.value
                    span.set_attribute("smartops.verification.status", verification.status.value)
                    span.set_attribute(
                        "smartops.verification.desired_replicas",
                        verification.desired_replicas or 0,
                    )
                    span.set_attribute(
                        "smartops.verification.ready_replicas",
                        verification.ready_replicas or 0,
                    )
                else:
                    span.set_attribute("smartops.verification.status", "NONE")

                # ------------------------------------------------------------------
                # 4) If success + verified → done
                # ------------------------------------------------------------------
                if (
                    result.success
                    and verification
                    and verification.status == VerificationStatus.SUCCESS
                ):
                    logger.info(
                        "ClosedLoopManager: action %s on %s/%s verified successfully in %.2fs",
                        action_req.type.value,
                        action_req.target.namespace,
                        action_req.target.name,
                        action_duration,
                    )
                    self._last_action_at[key] = now
                    CLOSED_LOOP_ACTIONS_TOTAL.labels(
                        type=action_type_label,
                        status="success",
                        verification_status=verification_status_label,
                    ).inc()
                    return

                # If here → verification failed
                logger.warning(
                    "ClosedLoopManager: action %s on %s/%s did not verify successfully "
                    "(success=%s, verification_status=%s)",
                    action_req.type.value,
                    action_req.target.namespace,
                    action_req.target.name,
                    result.success,
                    verification_status_label,
                )

                # Default retry logic
                retry_allowed = False
                if verification:
                    if verification.status == VerificationStatus.TIMED_OUT:
                        retry_allowed = True
                    elif verification.status == VerificationStatus.FAILED:
                        retry_allowed = False
                    else:
                        retry_allowed = True
                else:
                    retry_allowed = True

            # ------------------------------------------------------------------
            # 5) Exception handling, including guardrail exception logic
            # ------------------------------------------------------------------

            except Exception as exc:  # noqa: BLE001

                # GUARDRAIL → DO NOT RETRY
                if _is_guardrail_exception(exc):
                    reason = "replica_guardrail_http_exception"
                    logger.warning(
                        "ClosedLoopManager: guardrail blocked action %s on %s/%s, dropping permanently",
                        action_req.type.value,
                        action_req.target.namespace,
                        action_req.target.name,
                    )
                    span.record_exception(exc)
                    CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL.labels(
                        type=action_type_label,
                        reason=reason,
                    ).inc()
                    CLOSED_LOOP_ACTIONS_TOTAL.labels(
                        type=action_type_label,
                        status="failed",
                        verification_status="GUARDRAIL_BLOCKED",
                    ).inc()
                    return

                # NON-GUARDRAIL EXCEPTION → retry
                logger.exception(
                    "ClosedLoopManager: exception during execute_action: %s", exc
                )
                span.record_exception(exc)
                verification_status_label = "EXCEPTION"
                retry_allowed = True

                CLOSED_LOOP_ACTIONS_TOTAL.labels(
                    type=action_type_label,
                    status="exception",
                    verification_status=verification_status_label,
                ).inc()

            # ------------------------------------------------------------------
            # 6) Retry logic
            # ------------------------------------------------------------------
            if retry_allowed and item.attempt < self.max_retries:
                delay = self.base_backoff_seconds * (2 ** item.attempt)

                logger.info(
                    "ClosedLoopManager: scheduling retry for %s in %ds (attempt %d/%d)",
                    key,
                    delay,
                    item.attempt + 1,
                    self.max_retries,
                )

                CLOSED_LOOP_RETRIES_TOTAL.labels(type=action_type_label).inc()

                await asyncio.sleep(delay)

                retry_item = QueueItem(
                    kind=item.kind,
                    signal=item.signal,
                    attempt=item.attempt + 1,
                    enqueued_at=item.enqueued_at,
                )
                try:
                    self.queue.put_nowait(retry_item)
                except asyncio.QueueFull:
                    logger.warning(
                        "ClosedLoopManager: queue full while scheduling retry for %s, dropping",
                        key,
                    )
                CLOSED_LOOP_QUEUE_DEPTH.set(self.queue.qsize())
                return

            # ------------------------------------------------------------------
            # 7) No more retries → terminal failure
            # ------------------------------------------------------------------
            logger.error(
                "ClosedLoopManager: max retries reached or retry not allowed for %s, giving up",
                key,
            )
            CLOSED_LOOP_ACTIONS_TOTAL.labels(
                type=action_type_label,
                status="failed",
                verification_status=verification_status_label,
            ).inc()

    # ----------------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------------

    def _get_current_replicas(
        self, namespace: str, deployment_name: str
    ) -> Optional[int]:
        try:
            deployments = list_deployments(namespace=namespace)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "ClosedLoopManager: failed to list deployments in %s: %s",
                namespace,
                exc,
            )
            return None

        for dep in deployments:
            if dep.get("name") == deployment_name:
                replicas = dep.get("replicas")
                return replicas if replicas is not None else 0

        logger.warning(
            "ClosedLoopManager: deployment %s/%s not found while reading replicas",
            namespace,
            deployment_name,
        )
        return None

    # ----------------------------------------------------------------------
    # Mapping logic
    # ----------------------------------------------------------------------

    async def _map_anomaly_to_action(
        self, signal: AnomalySignal
    ) -> Optional[ActionRequest]:
        svc = signal.service
        ns = DEFAULT_NAMESPACE

        resolved_name = resolve_deployment_name(svc)
        logger.debug(
            "ClosedLoopManager: anomaly mapping service=%s resolved_name=%s",
            svc,
            resolved_name,
        )

        target = K8sTarget(kind="Deployment", namespace=ns, name=resolved_name)

        if signal.type == AnomalyType.RESOURCE:
            current = self._get_current_replicas(ns, resolved_name)
            if current is None:
                logger.warning(
                    "ClosedLoopManager: cannot derive current replicas for %s/%s, skipping SCALE",
                    ns,
                    resolved_name,
                )
                return None

            desired = current + 1

            return ActionRequest(
                type=ActionType.SCALE,
                target=target,
                dry_run=False,
                scale=ScaleParams(replicas=desired),
                reason=(
                    f"Closed-loop: resource anomaly windowId={signal.windowId} "
                    f"score={signal.score}"
                ),
                verify=True,
            )

        return ActionRequest(
            type=ActionType.RESTART,
            target=target,
            dry_run=False,
            reason=(
                f"Closed-loop: {signal.type.value} anomaly "
                f"windowId={signal.windowId} score={signal.score}"
            ),
            verify=True,
        )

    async def _map_rca_to_action(self, signal: RcaSignal) -> Optional[ActionRequest]:
        if not signal.rankedCauses:
            return None

        primary = signal.rankedCauses[0]
        cause = (primary.cause or "").lower()
        svc = primary.svc or signal.service or "erp-simulator"
        ns = DEFAULT_NAMESPACE

        resolved_name = resolve_deployment_name(svc)
        logger.debug(
            "ClosedLoopManager: RCA mapping service=%s resolved_name=%s cause=%s",
            svc,
            resolved_name,
            cause,
        )

        target = K8sTarget(kind="Deployment", namespace=ns, name=resolved_name)

        base_reason = (
            f"Closed-loop: RCA={cause} windowId={signal.windowId} "
            f"confidence={signal.confidence}"
        )

        if "memory_leak" in cause or "memory leak" in cause:
            return ActionRequest(
                type=ActionType.RESTART,
                target=target,
                dry_run=False,
                reason=base_reason,
                verify=True,
            )

        if "cpu" in cause or "saturation" in cause:
            current = self._get_current_replicas(ns, resolved_name)
            if current is None:
                logger.warning(
                    "ClosedLoopManager: cannot derive current replicas for %s/%s, skipping SCALE",
                    ns,
                    resolved_name,
                )
                return None

            desired = current + 1

            return ActionRequest(
                type=ActionType.SCALE,
                target=target,
                dry_run=False,
                scale=ScaleParams(replicas=desired),
                reason=base_reason,
                verify=True,
            )

        if "error" in cause or "high_error" in cause or "high_error_rate" in cause:
            return ActionRequest(
                type=ActionType.RESTART,
                target=target,
                dry_run=False,
                reason=base_reason,
                verify=True,
            )

        if "config" in cause or "bad_config" in cause or "misconfig" in cause:
            return ActionRequest(
                type=ActionType.RESTART,
                target=target,
                dry_run=False,
                reason=f"{base_reason} (placeholder: restart for now)",
                verify=True,
            )

        return ActionRequest(
            type=ActionType.RESTART,
            target=target,
            dry_run=False,
            reason=f"{base_reason} (fallback mapping)",
            verify=True,
        )


# Singleton instance used by app
closed_loop_manager = ClosedLoopManager()
