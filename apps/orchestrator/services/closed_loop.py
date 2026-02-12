import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional, Union, Dict, Tuple, List

from ..utils.policy_client import check_policy, PolicyDecisionType

from opentelemetry import trace
from prometheus_client import Counter, Histogram, Gauge

from ..models.signal_models import AnomalySignal, RcaSignal
from ..models.action_models import (
    ActionRequest,
    ActionType,
    K8sTarget,
    ScaleParams,
)
from ..models.verification_models import VerificationStatus
from ..services.k8s_core import list_deployments
from ..services import orchestrator_service  # use execute_action()

logger = logging.getLogger("smartops.closed_loop")
tracer = trace.get_tracer(__name__)

# --------------------------------------------------------------------------
# Prometheus metrics
# --------------------------------------------------------------------------

CLOSED_LOOP_SIGNALS_TOTAL = Counter(
    "orchestrator_closed_loop_signals_total",
    "Total number of signals processed by the closed-loop controller",
    ["kind", "result"],
)

CLOSED_LOOP_ACTIONS_TOTAL = Counter(
    "orchestrator_closed_loop_actions_total",
    "Total number of actions executed by the closed-loop controller",
    ["type", "status", "verification_status"],
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
    enqueued_at: float = field(default_factory=time.time)


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
    def __init__(
        self,
        cooldown_seconds: int = 300,
        max_retries: int = 2,
        base_backoff_seconds: int = 5,
    ) -> None:
        maxsize_env = int(os.getenv("CLOSED_LOOP_QUEUE_MAXSIZE", "0"))
        self.queue: "asyncio.Queue[QueueItem]" = asyncio.Queue(maxsize=maxsize_env)

        self.cooldown_seconds = cooldown_seconds
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds

        self.max_replicas: int = int(os.getenv("GUARDRAIL_MAX_REPLICAS", "8"))
        self.max_actions_per_hour: int = int(os.getenv("GUARDRAIL_MAX_ACTIONS_PER_HOUR", "6"))
        self.max_scale_increase_15m: int = int(os.getenv("GUARDRAIL_MAX_SCALE_INCREASE_15M", "3"))

        self._last_action_at: Dict[Tuple[str, str, str], float] = {}
        self._action_history: Dict[Tuple[str, str, str], List[float]] = {}
        self._scale_history: Dict[Tuple[str, str], List[Tuple[float, int]]] = {}

        self._worker_task: Optional[asyncio.Task] = None

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

    async def enqueue_anomaly(self, signal: AnomalySignal) -> None:
        item = QueueItem(kind="anomaly", signal=signal)
        try:
            self.queue.put_nowait(item)
            CLOSED_LOOP_SIGNALS_TOTAL.labels(kind="anomaly", result="accepted").inc()
        except asyncio.QueueFull:
            logger.warning(
                "ClosedLoopManager: queue full, dropping anomaly windowId=%s service=%s",
                getattr(signal, "windowId", ""),
                getattr(signal, "service", ""),
            )
            CLOSED_LOOP_SIGNALS_TOTAL.labels(kind="anomaly", result="dropped_queue_full").inc()
            return
        CLOSED_LOOP_QUEUE_DEPTH.set(self.queue.qsize())

    async def enqueue_rca(self, signal: RcaSignal) -> None:
        item = QueueItem(kind="rca", signal=signal)
        try:
            self.queue.put_nowait(item)
            CLOSED_LOOP_SIGNALS_TOTAL.labels(kind="rca", result="accepted").inc()
        except asyncio.QueueFull:
            logger.warning(
                "ClosedLoopManager: queue full, dropping RCA windowId=%s service=%s",
                getattr(signal, "windowId", ""),
                getattr(signal, "service", ""),
            )
            CLOSED_LOOP_SIGNALS_TOTAL.labels(kind="rca", result="dropped_queue_full").inc()
            return
        CLOSED_LOOP_QUEUE_DEPTH.set(self.queue.qsize())

    async def _worker(self) -> None:
        while True:
            CLOSED_LOOP_QUEUE_DEPTH.set(self.queue.qsize())
            item: QueueItem = await self.queue.get()
            try:
                await self._process_item(item)
            except Exception:  # noqa: BLE001
                logger.exception("ClosedLoopManager: unhandled error while processing item")
            finally:
                CLOSED_LOOP_DURATION_SECONDS.observe(time.time() - item.enqueued_at)
                self.queue.task_done()
                CLOSED_LOOP_QUEUE_DEPTH.set(self.queue.qsize())

    def _action_request_from_policy_plan(self, plan: dict) -> ActionRequest:
        target_dict = plan["target"]
        target = K8sTarget(
            kind=target_dict["kind"],
            namespace=target_dict["namespace"],
            name=target_dict["name"],
        )

        if plan["type"] == "restart":
            return ActionRequest(
                type=ActionType.RESTART,
                target=target,
                dry_run=plan.get("dry_run", False),
                verify=plan.get("verify", True),
                reason="Policy-engine decision",
            )

        if plan["type"] == "scale":
            return ActionRequest(
                type=ActionType.SCALE,
                target=target,
                dry_run=plan.get("dry_run", False),
                verify=plan.get("verify", True),
                scale=ScaleParams(replicas=plan["scale"]["replicas"]),
                reason="Policy-engine decision",
            )

        raise ValueError(f"Unknown action type from policy engine: {plan}")

    async def _process_item(self, item: QueueItem) -> None:
        with tracer.start_as_current_span("smartops.closed_loop.process_signal") as span:
            span.set_attribute("smartops.signal.kind", item.kind)
            span.set_attribute("smartops.signal.attempt", item.attempt)

            CLOSED_LOOP_SIGNALS_TOTAL.labels(kind=item.kind, result="processed").inc()

            # ------------------------------------------------------------------
            # 1) Ask Policy Engine for decision (NOW payload-driven via policy_client)
            # ------------------------------------------------------------------
            try:
                policy_decision = await check_policy(item.signal)
            except Exception as exc:
                logger.error("Policy Engine error: %s", exc)
                span.record_exception(exc)
                return

            if policy_decision.decision != PolicyDecisionType.ALLOW:
                logger.info("ClosedLoopManager: policy denied execution (%s)", policy_decision.reason)
                span.set_attribute("smartops.policy.decision", "deny")
                span.set_attribute("smartops.policy.reason", policy_decision.reason or "")
                CLOSED_LOOP_SIGNALS_TOTAL.labels(kind=item.kind, result="policy_denied").inc()
                return

            if not policy_decision.action_plan:
                logger.info("Policy allowed but no action plan returned")
                return

            action_req = self._action_request_from_policy_plan(policy_decision.action_plan)
            span.set_attribute("smartops.policy.decision", "allow")

            key = (action_req.target.namespace, action_req.target.name, action_req.type.value)
            ns = action_req.target.namespace
            deployment_name = action_req.target.name
            now = time.time()

            # ------------------------------------------------------------------
            # 2) Cooldown check
            # ------------------------------------------------------------------
            last = self._last_action_at.get(key)
            if last is not None and (now - last) < self.cooldown_seconds:
                logger.info("ClosedLoopManager: cooldown active for %s, skipping action", key)
                span.set_attribute("smartops.closed_loop.cooldown_skipped", True)
                return

            span.set_attribute("smartops.closed_loop.cooldown_skipped", False)

            # ------------------------------------------------------------------
            # 2b) Guardrails
            # ------------------------------------------------------------------
            action_type_label = action_req.type.value

            if self.max_actions_per_hour > 0:
                history = self._action_history.get(key, [])
                cutoff = now - 3600
                history = [t for t in history if t >= cutoff]
                self._action_history[key] = history
                if len(history) >= self.max_actions_per_hour:
                    reason = "max_actions_per_hour_exceeded"
                    logger.warning("ClosedLoopManager: guardrail %s for %s, skipping action", reason, key)
                    CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL.labels(type=action_type_label, reason=reason).inc()
                    return

            if action_req.type == ActionType.SCALE and action_req.scale is not None:
                current = self._get_current_replicas(ns, deployment_name)
                if current is not None:
                    desired = action_req.scale.replicas
                    delta = desired - current

                    if self.max_replicas > 0 and desired > self.max_replicas:
                        reason = "max_replicas_exceeded"
                        logger.warning(
                            "ClosedLoopManager: guardrail %s for %s/%s (desired=%d, limit=%d), skipping action",
                            reason, ns, deployment_name, desired, self.max_replicas,
                        )
                        CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL.labels(type=action_type_label, reason=reason).inc()
                        return

                    if delta > 0 and self.max_scale_increase_15m > 0:
                        sh_key = (ns, deployment_name)
                        shistory = self._scale_history.get(sh_key, [])
                        cutoff_15m = now - 900
                        shistory = [(t, d) for (t, d) in shistory if t >= cutoff_15m]
                        net_recent_inc = sum(max(0, d) for (_, d) in shistory)

                        if net_recent_inc + delta > self.max_scale_increase_15m:
                            reason = "max_scale_increase_15m_exceeded"
                            logger.warning(
                                "ClosedLoopManager: guardrail %s for %s/%s (recent_inc=%d, delta=%d, limit=%d), skipping action",
                                reason, ns, deployment_name, net_recent_inc, delta, self.max_scale_increase_15m,
                            )
                            CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL.labels(type=action_type_label, reason=reason).inc()
                            return

                        shistory.append((now, delta))
                        self._scale_history[sh_key] = shistory

            if self.max_actions_per_hour > 0:
                self._action_history.setdefault(key, []).append(now)

            # ------------------------------------------------------------------
            # 3) Execute via orchestrator
            # ------------------------------------------------------------------
            verification_status_label = "NONE"
            retry_allowed = False

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

                verification = result.verification
                if verification:
                    verification_status_label = verification.status.value

                if result.success and verification and verification.status == VerificationStatus.SUCCESS:
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

                # decide retry
                if verification:
                    retry_allowed = verification.status in {
                        VerificationStatus.TIMED_OUT,
                    }
                else:
                    retry_allowed = True

            except Exception as exc:  # noqa: BLE001
                if _is_guardrail_exception(exc):
                    reason = "replica_guardrail_http_exception"
                    logger.warning(
                        "ClosedLoopManager: guardrail blocked action %s on %s/%s, dropping permanently",
                        action_req.type.value,
                        action_req.target.namespace,
                        action_req.target.name,
                    )
                    CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL.labels(type=action_type_label, reason=reason).inc()
                    CLOSED_LOOP_ACTIONS_TOTAL.labels(
                        type=action_type_label,
                        status="failed",
                        verification_status="GUARDRAIL_BLOCKED",
                    ).inc()
                    return

                logger.exception("ClosedLoopManager: exception during execute_action: %s", exc)
                verification_status_label = "EXCEPTION"
                retry_allowed = True
                CLOSED_LOOP_ACTIONS_TOTAL.labels(
                    type=action_type_label,
                    status="exception",
                    verification_status=verification_status_label,
                ).inc()

            # ------------------------------------------------------------------
            # 4) Retry logic
            # ------------------------------------------------------------------
            if retry_allowed and item.attempt < self.max_retries:
                delay = self.base_backoff_seconds * (2 ** item.attempt)
                logger.info(
                    "ClosedLoopManager: scheduling retry for %s in %ds (attempt %d/%d)",
                    key, delay, item.attempt + 1, self.max_retries,
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
                    logger.warning("ClosedLoopManager: queue full while scheduling retry for %s, dropping", key)
                return

            logger.error("ClosedLoopManager: max retries reached or retry not allowed for %s, giving up", key)
            CLOSED_LOOP_ACTIONS_TOTAL.labels(
                type=action_type_label,
                status="failed",
                verification_status=verification_status_label,
            ).inc()

    def _get_current_replicas(self, namespace: str, deployment_name: str) -> Optional[int]:
        try:
            deployments = list_deployments(namespace=namespace)
        except Exception as exc:  # noqa: BLE001
            logger.error("ClosedLoopManager: failed to list deployments in %s: %s", namespace, exc)
            return None

        for dep in deployments:
            if dep.get("name") == deployment_name:
                replicas = dep.get("replicas")
                return replicas if replicas is not None else 0

        logger.warning("ClosedLoopManager: deployment %s/%s not found while reading replicas", namespace, deployment_name)
        return None


closed_loop_manager = ClosedLoopManager()
