import asyncio
import contextlib
import json
import logging
import os
import time
from . import k8s_core
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from opentelemetry import trace
from prometheus_client import Counter, Gauge, Histogram

from ..models.action_models import ActionRequest, ActionType, K8sTarget, ScaleParams
from ..models.signal_models import AnomalySignal, RcaSignal
from ..models.verification_models import VerificationStatus
from ..services import orchestrator_service  # use execute_action()
from ..services.k8s_core import list_deployments
from ..utils.policy_client import PolicyDecisionType, check_policy

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

CLOSED_LOOP_COOLDOWN_SKIPS_TOTAL = Counter(
    "orchestrator_closed_loop_cooldown_skips_total",
    "Number of times cooldown blocked execution before action",
    ["type"],
)

CLOSED_LOOP_POLICY_OUTCOMES_TOTAL = Counter(
    "orchestrator_closed_loop_policy_outcomes_total",
    "Policy engine outcomes observed by closed loop",
    ["kind", "decision", "reason"],
)


# --------------------------------------------------------------------------
# Queue item
# --------------------------------------------------------------------------

@dataclass
class QueueItem:
    kind: str  # "anomaly" or "rca"
    signal: Union[AnomalySignal, RcaSignal]
    attempt: int = 0
    enqueued_at: float = field(default_factory=time.time)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name, "")
    if not v:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int, min_value: Optional[int] = None) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        val = int(raw)
    except Exception:
        logger.warning("Invalid int env %s=%r, using default=%d", name, raw, default)
        val = default
    if min_value is not None:
        val = max(min_value, val)
    return val


def _env_json_dict(name: str) -> Dict[str, str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to parse %s: %s", name, exc)
    return {}


def _safe_model_dict(obj: Any) -> Dict[str, Any]:
    """Safely get a dict for pydantic v1/v2 models."""
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:  # noqa: BLE001
            return {}
    if hasattr(obj, "dict"):
        try:
            return obj.dict()
        except Exception:  # noqa: BLE001
            return {}
    try:
        return dict(obj)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return {}


def _resolve_service_name(kind: str, signal: Union[AnomalySignal, RcaSignal]) -> Optional[str]:
    """
    Return best-effort service identifier.

    - anomaly: signal.service
    - rca: prefer signal.service; fallback to rankedCauses[0].svc; fallback to metadata hints
    """
    if kind == "anomaly":
        svc = getattr(signal, "service", None)
        return str(svc).strip() if svc else None

    svc = getattr(signal, "service", None)
    if svc:
        s = str(svc).strip()
        return s if s else None

    ranked = getattr(signal, "rankedCauses", None) or []
    if ranked:
        top = ranked[0]
        top_svc = getattr(top, "svc", None)
        if top_svc:
            s = str(top_svc).strip()
            return s if s else None

    meta = getattr(signal, "metadata", None) or {}
    for k in ("service", "source_service", "root_service", "deployment", "deployment_name"):
        v = meta.get(k)
        if v:
            s = str(v).strip()
            if s:
                return s
    return None


def _is_guardrail_exception(exc: Exception) -> bool:
    """
    True if orchestrator blocked action due to replica/guardrail HTTPException.
    Detect:
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

    msg = str(getattr(exc, "detail", exc)).lower()
    return ("guardrail" in msg) or ("replica" in msg)


# --------------------------------------------------------------------------
# Closed loop
# --------------------------------------------------------------------------

class ClosedLoopManager:
    """
    Closed-loop controller.

    Key improvements for "error-proof" ops:
    - Cooldown configurable via env (CLOSED_LOOP_COOLDOWN_SECONDS), can be disabled for demo.
    - Guardrails toggleable (GUARDRAILS_ENABLED) and cooldown toggleable (COOLDOWN_ENABLED).
    - Guardrail decisions produce explicit reason + debug context in logs + metrics.
    - Optional per-signal config refresh (CLOSED_LOOP_REFRESH_CONFIG=true) so env changes apply after rollout,
      without needing code edits.
    - Memory bounds: bounded histories for action/scale/sustained windows.
    """

    def __init__(
        self,
        cooldown_seconds: Optional[int] = None,
        max_retries: int = 2,
        base_backoff_seconds: int = 5,
    ) -> None:
        # Static defaults + env config
        self.max_retries = max_retries
        self.base_backoff_seconds = base_backoff_seconds

        # runtime state
        self._worker_task: Optional[asyncio.Task] = None
        self._last_action_at: Dict[Tuple[str, str, str], float] = {}
        self._action_history: Dict[Tuple[str, str, str], List[float]] = {}
        self._scale_history: Dict[Tuple[str, str], List[Tuple[float, int]]] = {}

        # Sustained anomaly tracking
        self._anomaly_window_history: Dict[str, List[float]] = {}
        self._sustained_services: Dict[str, float] = {}

        # Load config
        self._config: Dict[str, Any] = {}
        self._load_config(cooldown_seconds_override=cooldown_seconds)

        # queue depends on config
        self.queue: "asyncio.Queue[QueueItem]" = asyncio.Queue(maxsize=self._config["queue_maxsize"])

        # service alias map
        self._service_alias_map: Dict[str, str] = _env_json_dict("SERVICE_ALIAS_MAP_JSON")
        if self._service_alias_map:
            logger.info("Loaded SERVICE_ALIAS_MAP_JSON keys=%s", list(self._service_alias_map.keys()))

    # ---------------------------
    # Config
    # ---------------------------

    def _load_config(self, cooldown_seconds_override: Optional[int] = None) -> None:
        # queue
        queue_maxsize = _env_int("CLOSED_LOOP_QUEUE_MAXSIZE", 0, min_value=0)

        # toggles
        refresh_config = _env_bool("CLOSED_LOOP_REFRESH_CONFIG", False)

        cooldown_enabled = _env_bool("COOLDOWN_ENABLED", True)
        guardrails_enabled = _env_bool("GUARDRAILS_ENABLED", True)

        # cooldown seconds (0 allowed)
        if cooldown_seconds_override is None:
            cooldown_seconds = _env_int("CLOSED_LOOP_COOLDOWN_SECONDS", 300, min_value=0)
        else:
            cooldown_seconds = max(0, int(cooldown_seconds_override))

        # guardrails
        max_replicas = _env_int("GUARDRAIL_MAX_REPLICAS", 8, min_value=0)
        max_actions_per_hour = _env_int("GUARDRAIL_MAX_ACTIONS_PER_HOUR", 6, min_value=0)
        max_scale_increase_15m = _env_int("GUARDRAIL_MAX_SCALE_INCREASE_15M", 3, min_value=0)
        max_scale_down_step = _env_int("GUARDRAIL_MAX_SCALE_DOWN_STEP", 0, min_value=0)

        # memory caps (keep these conservative)
        max_action_history = _env_int("GUARDRAIL_MAX_ACTION_HISTORY", 200, min_value=10)
        max_scale_history = _env_int("GUARDRAIL_MAX_SCALE_HISTORY", 200, min_value=10)

        # sustained gate
        sustained_gate_enabled = _env_bool("SUSTAINED_GATE_ENABLED", True)
        required_sustained_windows = _env_int("SUSTAINED_REQUIRED_WINDOWS", 3, min_value=1)
        sustained_window_seconds = _env_int("SUSTAINED_WINDOW_SECONDS", 30, min_value=1)
        max_history_per_service = _env_int("SUSTAINED_MAX_HISTORY", 50, min_value=10)

        self._config = {
            "queue_maxsize": queue_maxsize,
            "refresh_config": refresh_config,
            "cooldown_enabled": cooldown_enabled,
            "cooldown_seconds": cooldown_seconds,
            "guardrails_enabled": guardrails_enabled,
            "max_replicas": max_replicas,
            "max_actions_per_hour": max_actions_per_hour,
            "max_scale_increase_15m": max_scale_increase_15m,
            "max_scale_down_step": max_scale_down_step,
            "max_action_history": max_action_history,
            "max_scale_history": max_scale_history,
            "sustained_gate_enabled": sustained_gate_enabled,
            "required_sustained_windows": required_sustained_windows,
            "sustained_window_seconds": sustained_window_seconds,
            "max_history_per_service": max_history_per_service,
        }

    def _maybe_refresh_config(self) -> None:
        if self._config.get("refresh_config"):
            # Only refresh env-backed config. Keep queue as-is (cannot resize safely at runtime).
            self._load_config(cooldown_seconds_override=None)

    # ---------------------------
    # Service canonicalization
    # ---------------------------

    def _canonical_service(self, svc: Optional[str]) -> Optional[str]:
        if not svc:
            return None
        s = str(svc).strip()
        if not s:
            return None
        return self._service_alias_map.get(s, s)

    # ---------------------------
    # Lifecycle
    # ---------------------------

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

    # ---------------------------
    # Enqueue
    # ---------------------------

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

    # ---------------------------
    # Worker loop
    # ---------------------------

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

    # ---------------------------
    # Policy plan -> ActionRequest
    # ---------------------------

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

    # ---------------------------
    # Sustained gating
    # ---------------------------

    def _update_sustained_state_on_anomaly(self, service_name: str, now_ts: float) -> None:
        history = self._anomaly_window_history.get(service_name, [])
        cutoff = now_ts - self._config["sustained_window_seconds"]
        history = [t for t in history if t >= cutoff]
        history.append(now_ts)

        # bounded
        max_hist = self._config["max_history_per_service"]
        if max_hist > 0 and len(history) > max_hist:
            history = history[-max_hist:]

        self._anomaly_window_history[service_name] = history

        if len(history) < self._config["required_sustained_windows"]:
            self._sustained_services.pop(service_name, None)
            return

        self._sustained_services[service_name] = now_ts
        logger.info("SUSTAINED_ANOMALY | service=%s | windows=%d", service_name, len(history))

    def _auto_expire_sustained(self, now_ts: float) -> None:
        expired = [
            svc
            for svc, ts in self._sustained_services.items()
            if (now_ts - ts) > self._config["sustained_window_seconds"]
        ]
        for svc in expired:
            logger.info("SUSTAIN_EXPIRED_AUTO | service=%s", svc)
            self._sustained_services.pop(svc, None)

    # ---------------------------
    # Guardrails
    # ---------------------------

    def _prune_action_history(self, key: Tuple[str, str, str], now: float) -> List[float]:
        hist = self._action_history.get(key, [])
        cutoff = now - 3600
        hist = [t for t in hist if t >= cutoff]
        # hard bound
        max_len = self._config["max_action_history"]
        if max_len > 0 and len(hist) > max_len:
            hist = hist[-max_len:]
        self._action_history[key] = hist
        return hist

    def _prune_scale_history(self, sh_key: Tuple[str, str], now: float) -> List[Tuple[float, int]]:
        shistory = self._scale_history.get(sh_key, [])
        cutoff_15m = now - 900
        shistory = [(t, d) for (t, d) in shistory if t >= cutoff_15m]
        # hard bound
        max_len = self._config["max_scale_history"]
        if max_len > 0 and len(shistory) > max_len:
            shistory = shistory[-max_len:]
        self._scale_history[sh_key] = shistory
        return shistory

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

        logger.warning(
            "ClosedLoopManager: deployment %s/%s not found while reading replicas",
            namespace,
            deployment_name,
        )
        return None

    # ---------------------------
    # Main processing
    # ---------------------------

    async def _process_item(self, item: QueueItem) -> None:
        self._maybe_refresh_config()

        with tracer.start_as_current_span("smartops.closed_loop.process_signal") as span:
            span.set_attribute("smartops.signal.kind", item.kind)
            span.set_attribute("smartops.signal.attempt", item.attempt)

            raw = _safe_model_dict(item.signal)
            window_id = str(raw.get("windowId", ""))

            logger.info(
                "SIGNAL_RAW | kind=%s | type=%s | data=%s",
                item.kind,
                type(item.signal).__name__,
                raw,
            )
            CLOSED_LOOP_SIGNALS_TOTAL.labels(kind=item.kind, result="processed").inc()

            # --------------------------------------------------
            # Sustained anomaly gating
            # --------------------------------------------------
            svc_raw = _resolve_service_name(item.kind, item.signal)
            service_name = self._canonical_service(svc_raw)

            if self._config["sustained_gate_enabled"]:
                now_ts = time.time()
                self._auto_expire_sustained(now_ts)

                if item.kind == "rca" and not service_name:
                    logger.info("RCA_SKIPPED_NO_SERVICE | windowId=%s", window_id)
                    CLOSED_LOOP_SIGNALS_TOTAL.labels(kind="rca", result="skipped_no_service").inc()
                    return

                if service_name:
                    logger.info(
                        "SUSTAIN_DEBUG | enabled=%s | kind=%s | service=%s | sustained_keys=%s",
                        self._config["sustained_gate_enabled"],
                        item.kind,
                        service_name,
                        list(self._sustained_services.keys()),
                    )

                if service_name and item.kind == "anomaly":
                    self._update_sustained_state_on_anomaly(service_name, now_ts)

                if service_name and item.kind == "rca":
                    sustained_at = self._sustained_services.get(service_name)
                    if not sustained_at:
                        logger.info("RCA_SKIPPED_NOT_SUSTAINED | service=%s", service_name)
                        CLOSED_LOOP_SIGNALS_TOTAL.labels(kind="rca", result="skipped_not_sustained").inc()
                        return

                    if (now_ts - sustained_at) > self._config["sustained_window_seconds"]:
                        logger.info("RCA_SKIPPED_SUSTAIN_EXPIRED | service=%s", service_name)
                        CLOSED_LOOP_SIGNALS_TOTAL.labels(kind="rca", result="skipped_sustain_expired").inc()
                        self._sustained_services.pop(service_name, None)
                        return

            # ------------------------------------------------------------------
            # 1) Ask Policy Engine
            # ------------------------------------------------------------------
            try:
                policy_decision = await check_policy(item.signal)
            except Exception as exc:
                logger.error("Policy Engine error: %s", exc)
                span.record_exception(exc)
                CLOSED_LOOP_SIGNALS_TOTAL.labels(kind=item.kind, result="policy_error").inc()
                CLOSED_LOOP_POLICY_OUTCOMES_TOTAL.labels(kind=item.kind, decision="error", reason="exception").inc()
                return

            # record policy outcome metrics
            decision_str = "allow" if policy_decision.decision == PolicyDecisionType.ALLOW else "deny"
            reason_str = (policy_decision.reason or "").strip() or ("allowed" if decision_str == "allow" else "unknown")
            CLOSED_LOOP_POLICY_OUTCOMES_TOTAL.labels(kind=item.kind, decision=decision_str, reason=reason_str[:80]).inc()

            if policy_decision.decision != PolicyDecisionType.ALLOW:
                logger.info("ClosedLoopManager: policy denied execution (%s)", policy_decision.reason)
                span.set_attribute("smartops.policy.decision", "deny")
                span.set_attribute("smartops.policy.reason", policy_decision.reason or "")
                CLOSED_LOOP_SIGNALS_TOTAL.labels(kind=item.kind, result="policy_denied").inc()
                return

            if not policy_decision.action_plan:
                logger.info("Policy allowed but no action plan returned")
                CLOSED_LOOP_SIGNALS_TOTAL.labels(kind=item.kind, result="policy_allowed_no_plan").inc()
                return

            action_req = self._action_request_from_policy_plan(policy_decision.action_plan)
            span.set_attribute("smartops.policy.decision", "allow")
            span.set_attribute("smartops.policy.policy", getattr(policy_decision, "policy", "") or "")

            action_type_label = action_req.type.value
            ns = action_req.target.namespace
            deployment_name = action_req.target.name
            now = time.time()
            key = (ns, deployment_name, action_type_label)

            # ------------------------------------------------------------------
            # 2) Cooldown check (configurable)
            # ------------------------------------------------------------------
            if self._config["cooldown_enabled"] and self._config["cooldown_seconds"] > 0:
                last = self._last_action_at.get(key)
                if last is not None and (now - last) < self._config["cooldown_seconds"]:
                    logger.info(
                        "ClosedLoopManager: cooldown active for %s (elapsed=%.2fs < %ds), skipping action",
                        key,
                        (now - last),
                        self._config["cooldown_seconds"],
                    )
                    span.set_attribute("smartops.closed_loop.cooldown_skipped", True)
                    CLOSED_LOOP_COOLDOWN_SKIPS_TOTAL.labels(type=action_type_label).inc()
                    CLOSED_LOOP_ACTIONS_TOTAL.labels(
                        type=action_type_label,
                        status="skipped",
                        verification_status="COOLDOWN",
                    ).inc()
                    return
            span.set_attribute("smartops.closed_loop.cooldown_skipped", False)

            # ------------------------------------------------------------------
            # 3) Guardrails (configurable)
            # ------------------------------------------------------------------
            if self._config["guardrails_enabled"]:
                # per-hour action limit
                if self._config["max_actions_per_hour"] > 0:
                    hist = self._prune_action_history(key, now)
                    if len(hist) >= self._config["max_actions_per_hour"]:
                        reason = "max_actions_per_hour_exceeded"
                        logger.warning(
                            "ClosedLoopManager: guardrail %s for %s (count_last_hour=%d limit=%d), skipping action",
                            reason,
                            key,
                            len(hist),
                            self._config["max_actions_per_hour"],
                        )
                        CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL.labels(type=action_type_label, reason=reason).inc()
                        CLOSED_LOOP_ACTIONS_TOTAL.labels(
                            type=action_type_label,
                            status="skipped",
                            verification_status="GUARDRAIL",
                        ).inc()
                        return

                # scaling-specific guardrails
                if action_req.type == ActionType.SCALE and action_req.scale is not None:
                    current = self._get_current_replicas(ns, deployment_name)
                    desired = action_req.scale.replicas
                    if current is not None:
                        delta = desired - current

                        # scale-down step limiter
                        if self._config["max_scale_down_step"] > 0 and delta < 0 and abs(delta) > self._config["max_scale_down_step"]:
                            new_desired = max(0, current - self._config["max_scale_down_step"])
                            logger.warning(
                                "ClosedLoopManager: scale-down limited for %s/%s (current=%d desired=%d step=%d -> new_desired=%d)",
                                ns,
                                deployment_name,
                                current,
                                desired,
                                self._config["max_scale_down_step"],
                                new_desired,
                            )
                            action_req.scale.replicas = new_desired
                            desired = new_desired
                            delta = desired - current

                        # max replicas
                        if self._config["max_replicas"] > 0 and desired > self._config["max_replicas"]:
                            reason = "max_replicas_exceeded"
                            logger.warning(
                                "ClosedLoopManager: guardrail %s for %s/%s (current=%d desired=%d limit=%d), skipping action",
                                reason,
                                ns,
                                deployment_name,
                                current,
                                desired,
                                self._config["max_replicas"],
                            )
                            CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL.labels(type=action_type_label, reason=reason).inc()
                            CLOSED_LOOP_ACTIONS_TOTAL.labels(
                                type=action_type_label,
                                status="skipped",
                                verification_status="GUARDRAIL",
                            ).inc()
                            return

                        # max net increase in 15m
                        if delta > 0 and self._config["max_scale_increase_15m"] > 0:
                            sh_key = (ns, deployment_name)
                            shistory = self._prune_scale_history(sh_key, now)
                            net_recent_inc = sum(max(0, d) for (_, d) in shistory)

                            if net_recent_inc + delta > self._config["max_scale_increase_15m"]:
                                reason = "max_scale_increase_15m_exceeded"
                                logger.warning(
                                    "ClosedLoopManager: guardrail %s for %s/%s (recent_inc=%d delta=%d limit=%d), skipping action",
                                    reason,
                                    ns,
                                    deployment_name,
                                    net_recent_inc,
                                    delta,
                                    self._config["max_scale_increase_15m"],
                                )
                                CLOSED_LOOP_GUARDRAIL_BLOCKS_TOTAL.labels(type=action_type_label, reason=reason).inc()
                                CLOSED_LOOP_ACTIONS_TOTAL.labels(
                                    type=action_type_label,
                                    status="skipped",
                                    verification_status="GUARDRAIL",
                                ).inc()
                                return

                            # record this intended increase
                            shistory.append((now, delta))
                            # hard bound (already pruned)
                            max_len = self._config["max_scale_history"]
                            if max_len > 0 and len(shistory) > max_len:
                                shistory = shistory[-max_len:]
                            self._scale_history[sh_key] = shistory

                # record action in per-hour history (only if it passed guardrails)
                if self._config["max_actions_per_hour"] > 0:
                    hist2 = self._action_history.get(key, [])
                    hist2.append(now)
                    # bound
                    max_len = self._config["max_action_history"]
                    if max_len > 0 and len(hist2) > max_len:
                        hist2 = hist2[-max_len:]
                    self._action_history[key] = hist2

            # ------------------------------------------------------------------
            # 4) Execute via orchestrator
            # ------------------------------------------------------------------
            verification_status_label = "NONE"
            retry_allowed = False
            action_duration = 0.0

            try:
                logger.info(
                    "ClosedLoopManager: executing %s on %s/%s (attempt=%d windowId=%s)",
                    action_req.type.value,
                    action_req.target.namespace,
                    action_req.target.name,
                    item.attempt,
                    window_id,
                )

                start_action = time.time()
                result = await orchestrator_service.execute_action(action_req)
                action_duration = time.time() - start_action

                CLOSED_LOOP_ACTION_DURATION_SECONDS.observe(action_duration)

                verification = result.verification
                if verification:
                    verification_status_label = verification.status.value

                if result.success and verification and verification.status == VerificationStatus.SUCCESS:
                    # --- Production-grade: persist remediation state (prevents stage races) ---
                    try:
                        if action_req.type.value == "scale":
                            # action_req.scale.replicas is the target replicas
                            reps = None
                            if getattr(action_req, "scale", None) and getattr(action_req.scale, "replicas", None) is not None:
                                reps = int(action_req.scale.replicas)

                            if reps in (4, 6):
                                level = "1" if reps == 4 else "2"
                                patch_body = {
                                    "metadata": {
                                        "annotations": {
                                            "smartops.io/remediation-level": level
                                        }
                                    }
                                }
                                k8s_core.patch_deployment(
                                    name=action_req.target.name,
                                    patch_body=patch_body,
                                    namespace=action_req.target.namespace,
                                    dry_run=False,
                                )
                                logger.info(
                                    "ClosedLoopManager: remediation-level persisted after verify (deployment=%s level=%s windowId=%s)",
                                    action_req.target.name, level, window_id
                                )
                    except Exception:
                        logger.exception("ClosedLoopManager: failed to persist remediation-level (best-effort).")
                    logger.info(
                        "ClosedLoopManager: action %s on %s/%s verified successfully in %.2fs",
                        action_req.type.value,
                        action_req.target.namespace,
                        action_req.target.name,
                        action_duration,
                    )

                    logger.info(
                        "CLOSED_LOOP_SUMMARY | service=%s | action=%s | namespace=%s | duration=%.2fs | result=SUCCESS | attempt=%d | windowId=%s",
                        action_req.target.name,
                        action_req.type.value,
                        action_req.target.namespace,
                        action_duration,
                        item.attempt + 1,
                        window_id,
                    )

                    # mark last action time for cooldown
                    self._last_action_at[key] = now

                    CLOSED_LOOP_ACTIONS_TOTAL.labels(
                        type=action_type_label,
                        status="success",
                        verification_status=verification_status_label,
                    ).inc()
                    return

                # decide retry
                if verification:
                    retry_allowed = verification.status in {VerificationStatus.TIMED_OUT}
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
                    logger.info(
                        "CLOSED_LOOP_SUMMARY | service=%s | action=%s | namespace=%s | duration=0.00s | result=GUARDRAIL_BLOCKED | attempt=%d | windowId=%s",
                        action_req.target.name,
                        action_req.type.value,
                        action_req.target.namespace,
                        item.attempt + 1,
                        window_id,
                    )
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
            # 5) Retry logic
            # ------------------------------------------------------------------
            if retry_allowed and item.attempt < self.max_retries:
                delay = self.base_backoff_seconds * (2 ** item.attempt)
                logger.info(
                    "ClosedLoopManager: scheduling retry for %s in %ds (attempt %d/%d windowId=%s)",
                    key,
                    delay,
                    item.attempt + 1,
                    self.max_retries,
                    window_id,
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
            logger.info(
                "CLOSED_LOOP_SUMMARY | service=%s | action=%s | namespace=%s | duration=%.2fs | result=FAILED | attempt=%d | windowId=%s",
                action_req.target.name,
                action_req.type.value,
                action_req.target.namespace,
                action_duration,
                item.attempt + 1,
                window_id,
            )


closed_loop_manager = ClosedLoopManager()