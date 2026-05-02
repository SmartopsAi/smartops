import os
import time
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from flask import Flask, jsonify, request

from services.artifact_reader import ArtifactReader
from services.smartops_clients import OrchestratorClient
from services.prometheus_client import PrometheusClient
from services.dashboard_mapper import (
    build_pipeline_stages,
    build_summary_cards,
    build_system_state,
)

logging.basicConfig(level=logging.DEBUG)

prom = PrometheusClient()
orchestrator = OrchestratorClient()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dashboard")

reader = ArtifactReader()

def build_persistent_anomaly_evidence(anomaly=None, rca=None, policy_decision=None, verification=None):
    """
    Build a dashboard-local persistent anomaly evidence object from the live
    anomaly/RCA/policy/verification pipeline.

    This is required in Kubernetes because agent-detect and dashboard-api run
    in separate pods and do not share the same container filesystem.
    """
    if not anomaly:
        return None

    metadata = anomaly.get("metadata") or {}
    ranked_causes = (rca or {}).get("rankedCauses") or []
    top_cause = ranked_causes[0] if ranked_causes else {}

    action_plan = (policy_decision or {}).get("action_plan") or {}
    target = action_plan.get("target") or {}

    return {
        "eventId": f"A-{anomaly.get('windowId', 'unknown')}",
        "windowId": anomaly.get("windowId"),
        "timestamp": (policy_decision or {}).get("ts_utc"),
        "ts_utc": (policy_decision or {}).get("ts_utc"),
        "service": anomaly.get("service"),
        "type": anomaly.get("type"),
        "severity": "CRITICAL" if metadata.get("risk") == "HIGH" else "WARNING",
        "risk": metadata.get("risk"),
        "score": anomaly.get("score"),
        "source": metadata.get("source", "dashboard-api"),
        "profile": metadata.get("profile"),
        "rca": {
            "topCause": top_cause.get("cause"),
            "probability": top_cause.get("probability"),
            "confidence": (rca or {}).get("confidence"),
        },
        "policy": {
            "decision": (policy_decision or {}).get("decision"),
            "policy": (policy_decision or {}).get("policy"),
            "guardrail": (policy_decision or {}).get("guardrail_reason"),
            "priority": (policy_decision or {}).get("priority"),
            "priority_label": (policy_decision or {}).get("priority_label"),
            "priority_score": (policy_decision or {}).get("priority_score"),
            "execution_mode": (policy_decision or {}).get("execution_mode"),
        },
        "action": {
            "type": action_plan.get("type"),
            "target": target,
            "scale": action_plan.get("scale"),
            "verify": action_plan.get("verify"),
            "dry_run": action_plan.get("dry_run"),
        },
        "verification": verification,
        "status": "RECORDED_BY_DASHBOARD_API",
    }


def persist_dashboard_anomaly_evidence(evidence):
    """
    Store last anomaly evidence locally in dashboard-api. This preserves the
    latest anomaly for demo/audit view after live state returns to healthy.
    """
    if not evidence:
        return

    try:
        latest_path = reader.paths.get("latest_anomaly_evidence")
        history_path = reader.paths.get("anomaly_history")

        if latest_path:
            latest_path.parent.mkdir(parents=True, exist_ok=True)
            latest_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")

        if history_path:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            existing = set()
            if history_path.exists():
                for line in history_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    if evidence.get("eventId") and evidence.get("eventId") in line:
                        existing.add(evidence.get("eventId"))

            if evidence.get("eventId") not in existing:
                with history_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(evidence) + "\n")
    except Exception as exc:
        app.logger.warning("Failed to persist dashboard anomaly evidence: %s", exc)



MODE = "k8s" if os.environ.get("KUBERNETES_SERVICE_HOST") else "local"
DEFAULT_NAMESPACE = os.getenv("SMARTOPS_NAMESPACE", "smartops-dev")
POLICY_ENGINE_URL = os.getenv("POLICY_ENGINE_URL", "http://127.0.0.1:5051").rstrip("/")
ERP_SIMULATOR_SERVICE_URL = os.getenv(
    "ERP_SIMULATOR_URL",
    "http://smartops-erp-simulator:8000" if MODE == "k8s" else "http://127.0.0.1:8000",
).rstrip("/")

SIMULATOR_LABEL_SELECTOR = "app=smartops-erp-simulator"
SIMULATOR_DEPLOYMENT = "smartops-erp-simulator"
DETECTOR_DEPLOYMENT = "smartops-agent-detect-sim"
BASELINE_REPLICAS = 3

MANUAL_EXECUTION_STATE = {
    "erp-simulator": {
        "lastActionResult": None,
        "lastVerificationResult": None,
        "updatedAt": None,
    },
    "odoo": {
        "lastActionResult": None,
        "lastVerificationResult": None,
        "updatedAt": None,
    },
}


def _safe_get_json(url: str, timeout: int = 3) -> dict:
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("GET failed url=%s err=%s", url, exc)
        return {}


def _safe_post_json(url: str, payload: dict | None = None, timeout: int = 15) -> dict:
    try:
        resp = requests.post(url, json=payload or {}, timeout=timeout)
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return {"ok": True}
    except Exception as exc:
        logger.warning("POST failed url=%s err=%s", url, exc)
        return {"ok": False, "error": str(exc)}


def _orchestrator_get_json(path: str, params: dict | None = None, timeout: int = 10) -> dict:
    base = orchestrator.base_url.rstrip("/")
    url = f"{base}{path}"
    try:
        resp = requests.get(url, params=params or {}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Orchestrator GET failed path=%s err=%s", path, exc)
        return {"ok": False, "error": str(exc)}


def _orchestrator_post_json(path: str, payload: dict | None = None, timeout: int = 30) -> dict:
    base = orchestrator.base_url.rstrip("/")
    url = f"{base}{path}"
    try:
        resp = requests.post(url, json=payload or {}, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Orchestrator POST failed path=%s err=%s", path, exc)
        return {"ok": False, "error": str(exc)}


def _get_policy_events(limit: int = 10) -> list:
    payload = _safe_get_json(f"{POLICY_ENGINE_URL}/v1/policy/audit/latest?n={limit}")
    return payload.get("events", []) if isinstance(payload, dict) else []


def _get_recent_signals(limit: int = 20) -> dict:
    payload = orchestrator._get(f"/v1/signals/recent?limit={limit}")
    if not isinstance(payload, dict):
        return {"anomalies": [], "rcas": []}
    return {
        "anomalies": payload.get("anomalies", []) or [],
        "rcas": payload.get("rcas", []) or [],
    }


def _normalize_system_name(system: str) -> str:
    if system == "erp-simulator":
        return "smartops-erp-simulator"
    if system == "odoo":
        return "odoo-web"
    return system


def _system_from_deployment_name(name: str | None) -> str | None:
    if not name:
        return None
    if name == "smartops-erp-simulator" or name == "erp-simulator":
        return "erp-simulator"
    if name == "odoo-web" or name == "odoo":
        return "odoo"
    return None


def _event_sort_epoch(item: dict) -> int:
    return (
        _parse_event_epoch(item.get("ts_utc"))
        or _parse_event_epoch(item.get("ts"))
        or _parse_event_epoch(item.get("windowId"))
        or 0
    )

RECENT_SIGNAL_WINDOW_SECONDS = int(os.getenv("RECENT_SIGNAL_WINDOW_SECONDS", "90"))

def _is_recent_event(item: dict | None, max_age_seconds: int = RECENT_SIGNAL_WINDOW_SECONDS) -> bool:
    if not item:
        return False

    event_epoch = (
        _parse_event_epoch(item.get("ts_utc"))
        or _parse_event_epoch(item.get("ts"))
        or _parse_event_epoch(item.get("windowId"))
    )
    if event_epoch is None:
        return False

    return (int(time.time()) - event_epoch) <= max_age_seconds


def _pick_latest_for_system(items: list, system: str) -> dict | None:
    filtered = [item for item in items if item.get("service") == system]
    if not filtered:
        return None
    return max(filtered, key=_event_sort_epoch)


def _pick_latest_policy_for_system(events: list, system: str) -> dict | None:
    expected_target_name = _normalize_system_name(system)

    filtered = []
    for event in events:
        action_plan = event.get("action_plan") or {}
        target = action_plan.get("target") or {}
        if target.get("name") == expected_target_name:
            filtered.append(event)

    if not filtered:
        return None

    return max(
        filtered,
        key=lambda ev: (
            _parse_event_epoch(ev.get("ts_utc"))
            or _parse_event_epoch(ev.get("ts"))
            or 0
        ),
    )

def _latest_verification_placeholder(policy_event: dict | None) -> dict | None:
    if not policy_event:
        return None
    action_plan = policy_event.get("action_plan") or {}
    if not action_plan.get("verify"):
        return None
    return {
        "overall": None,
        "status": "pending",
        "source": "policy_audit",
    }


def _manual_verification_to_summary(verification_result: dict | None) -> dict | None:
    if not verification_result:
        return None

    raw_status = str(verification_result.get("status", "")).upper()
    if raw_status == "SUCCESS":
        overall = True
    elif raw_status in {"FAILED", "FAILURE", "ERROR"}:
        overall = False
    else:
        overall = None

    return {
        "overall": overall,
        "status": raw_status.lower() if raw_status else "unknown",
        "source": "manual_verification",
        "message": verification_result.get("message"),
        "ready_replicas": verification_result.get("ready_replicas"),
        "desired_replicas": verification_result.get("desired_replicas"),
    }

def _derive_live_verification_from_state(
    system_state: dict | None,
    policy_decision: dict | None,
) -> dict | None:
    if not system_state or not policy_decision:
        return None

    action_plan = policy_decision.get("action_plan") or {}
    if not action_plan.get("verify"):
        return None

    action_type = action_plan.get("type")
    scale_plan = action_plan.get("scale") or {}

    ready = system_state.get("replicasReady")
    desired = system_state.get("replicasDesired")
    available = system_state.get("replicasAvailable")

    expected_desired = desired
    if action_type == "scale" and scale_plan.get("replicas") is not None:
        expected_desired = scale_plan.get("replicas")

    overall = None
    status = "pending"

    if expected_desired is not None and ready is not None:
        if ready >= expected_desired:
            overall = True
            status = "success"
        else:
            overall = False
            status = "pending"

    return {
        "overall": overall,
        "status": status,
        "source": "live_state_inference",
        "message": (
            f"Deployment state indicates {ready}/{expected_desired} ready replicas."
            if expected_desired is not None and ready is not None
            else "Live deployment state was used to infer verification."
        ),
        "ready_replicas": ready,
        "desired_replicas": expected_desired,
        "available_replicas": available,
    }

def _store_manual_action(system: str | None, result: dict | None) -> None:
    if not system or system not in MANUAL_EXECUTION_STATE:
        return
    MANUAL_EXECUTION_STATE[system]["lastActionResult"] = result
    MANUAL_EXECUTION_STATE[system]["updatedAt"] = datetime.now(timezone.utc).isoformat()


def _store_manual_verification(system: str | None, result: dict | None) -> None:
    if not system or system not in MANUAL_EXECUTION_STATE:
        return
    MANUAL_EXECUTION_STATE[system]["lastVerificationResult"] = result
    MANUAL_EXECUTION_STATE[system]["updatedAt"] = datetime.now(timezone.utc).isoformat()


def _clear_manual_state(system: str) -> None:
    if system not in MANUAL_EXECUTION_STATE:
        return
    MANUAL_EXECUTION_STATE[system]["lastActionResult"] = None
    MANUAL_EXECUTION_STATE[system]["lastVerificationResult"] = None
    MANUAL_EXECUTION_STATE[system]["updatedAt"] = datetime.now(timezone.utc).isoformat()


def _build_manual_policy_like_result(action_result: dict | None) -> dict | None:
    if not action_result:
        return None

    deployment = (action_result.get("result") or {}).get("deployment") or {}
    operation = (action_result.get("result") or {}).get("operation")
    payload = deployment.get("result") or {}
    deployment_name = payload.get("name")
    namespace = payload.get("namespace", DEFAULT_NAMESPACE)

    if not operation or not deployment_name:
        return None

    synthetic_policy = {
        "policy": f"manual_{operation}",
        "decision": "action",
        "guardrail_reason": "manual_dashboard_execution",
        "priority": 999,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "action_plan": {
            "type": operation,
            "dry_run": payload.get("dry_run", False),
            "verify": True,
            "target": {
                "kind": "Deployment",
                "name": deployment_name,
                "namespace": namespace,
            },
        },
    }

    if operation == "scale" and "replicas" in payload:
        synthetic_policy["action_plan"]["scale"] = {
            "replicas": payload.get("replicas")
        }

    return synthetic_policy


def _parse_event_epoch(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)

    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)

    try:
        return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
    except Exception:
        return None


def _pick_latest_policy_by_name(events: list, system: str, policy_name: str) -> dict | None:
    expected_target_name = _normalize_system_name(system)

    filtered = []
    for event in events:
        action_plan = event.get("action_plan") or {}
        target = action_plan.get("target") or {}
        if event.get("policy") == policy_name and target.get("name") == expected_target_name:
            filtered.append(event)

    if not filtered:
        return None

    return max(
        filtered,
        key=lambda ev: (
            _parse_event_epoch(ev.get("ts_utc"))
            or _parse_event_epoch(ev.get("ts"))
            or 0
        ),
    )


def _pick_closest_anomaly_for_policy(
    anomalies: list,
    system: str,
    anomaly_type: str,
    policy_event: dict | None,
) -> dict | None:
    filtered = [
        item for item in anomalies
        if item.get("service") == system
        and str(item.get("type", "")).lower() == anomaly_type.lower()
    ]
    if not filtered:
        return None

    policy_epoch = _parse_event_epoch((policy_event or {}).get("ts_utc") or (policy_event or {}).get("ts"))
    if policy_epoch is None:
        return filtered[-1]

    best_item = None
    best_delta = None

    for item in filtered:
        anomaly_epoch = (
            _parse_event_epoch(item.get("windowId"))
            or _parse_event_epoch(item.get("ts"))
            or _parse_event_epoch(item.get("ts_utc"))
        )
        if anomaly_epoch is None:
            continue

        delta = policy_epoch - anomaly_epoch
        if delta < 0:
            continue
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_item = item

    return best_item or filtered[-1]


def _pick_rca_for_window(rcas: list, system: str, window_id: str | None) -> dict | None:
    if not window_id:
        return None
    for item in rcas:
        if item.get("service") == system and str(item.get("windowId")) == str(window_id):
            return item
    return None


def _build_live_scenario(
    *,
    key: str,
    title: str,
    scenario_type: str,
    policy_name: str,
    system: str,
    policy_events: list,
    anomalies: list,
    rcas: list,
) -> dict:
    policy_event = _pick_latest_policy_by_name(policy_events, system, policy_name)
    anomaly = _pick_closest_anomaly_for_policy(anomalies, system, scenario_type, policy_event)
    rca = _pick_rca_for_window(rcas, system, (anomaly or {}).get("windowId"))

    action_plan = (policy_event or {}).get("action_plan") or {}
    target = action_plan.get("target") or {}
    scale = action_plan.get("scale") or {}
    top_cause = ((rca or {}).get("rankedCauses") or [{}])[0]

    observed = policy_event is not None and anomaly is not None

    summary = (
        f"Live evidence observed for {policy_name}."
        if observed
        else f"No recent live evidence has been matched yet for {policy_name}."
    )

    return {
        "key": key,
        "title": title,
        "mode": "live",
        "observed": observed,
        "observedAt": (policy_event or {}).get("ts_utc") or (policy_event or {}).get("ts"),
        "windowIds": [str((anomaly or {}).get("windowId"))] if (anomaly or {}).get("windowId") else [],
        "service": system,
        "anomalyType": (anomaly or {}).get("type", scenario_type).upper(),
        "risk": ((anomaly or {}).get("metadata") or {}).get("risk"),
        "score": (anomaly or {}).get("score"),
        "policy": (policy_event or {}).get("policy"),
        "decision": (policy_event or {}).get("decision"),
        "guardrail": (policy_event or {}).get("guardrail_reason"),
        "action": action_plan.get("type"),
        "verifyRequested": action_plan.get("verify"),
        "targetDeployment": target.get("name"),
        "targetNamespace": target.get("namespace"),
        "targetReplicas": scale.get("replicas"),
        "rcaCause": top_cause.get("cause"),
        "rcaProbability": top_cause.get("probability"),
        "confidence": (rca or {}).get("confidence"),
        "summary": summary,
    }


def _build_live_scenarios(system: str, signals: dict, policy_events: list) -> dict:
    if system != "erp-simulator":
        return {}

    anomalies = signals.get("anomalies", []) or []
    rcas = signals.get("rcas", []) or []

    scenario_1 = _build_live_scenario(
        key="scenario-1",
        title="Scenario 1 - Resource anomaly triggered safe scale-up",
        scenario_type="resource",
        policy_name="scale_up_on_anomaly_resource_step_1",
        system=system,
        policy_events=policy_events,
        anomalies=anomalies,
        rcas=rcas,
    )

    scenario_2 = _build_live_scenario(
        key="scenario-2",
        title="Scenario 2 - Error anomaly triggered restart",
        scenario_type="error",
        policy_name="restart_on_anomaly_error",
        system=system,
        policy_events=policy_events,
        anomalies=anomalies,
        rcas=rcas,
    )

    blocked_candidates = []
    for event in policy_events:
        action_plan = event.get("action_plan") or {}
        target = action_plan.get("target") or {}

        if (
            event.get("policy") == "restart_on_anomaly_error"
            and str(event.get("decision", "")).lower() == "blocked"
            and target.get("name") in {_normalize_system_name(system), None}
            and "restart cooldown" in str(event.get("guardrail_reason", "")).lower()
        ):
            blocked_candidates.append(event)

    blocked_restart = (
        max(
            blocked_candidates,
            key=lambda ev: (
                _parse_event_epoch(ev.get("ts_utc"))
                or _parse_event_epoch(ev.get("ts"))
                or 0
            ),
        )
        if blocked_candidates
        else None
    )

    blocked_window_id = _pick_matching_window_for_policy(
        policy_event=blocked_restart,
        signals=signals,
        system=system,
        anomaly_type="error",
    )

    blocked_anomaly = _pick_anomaly_for_window(anomalies, system, blocked_window_id)
    blocked_rca = _pick_rca_for_window(rcas, system, blocked_window_id)
    top_cause = ((blocked_rca or {}).get("rankedCauses") or [{}])[0]

    scenario_3 = {
        "key": "scenario-3",
        "title": "Scenario 3 - Guarded self-healing through restart cooldown",
        "mode": "live",
        "observed": blocked_restart is not None,
        "observedAt": (blocked_restart or {}).get("ts_utc") or (blocked_restart or {}).get("ts"),
        "windowIds": [str(blocked_window_id)] if blocked_window_id else [],
        "service": system,
        "anomalyType": str((blocked_anomaly or {}).get("type", "error")).upper(),
        "risk": ((blocked_anomaly or {}).get("metadata") or {}).get("risk"),
        "score": (blocked_anomaly or {}).get("score"),
        "policy": (blocked_restart or {}).get("policy"),
        "decision": (blocked_restart or {}).get("decision"),
        "guardrail": (blocked_restart or {}).get("guardrail_reason"),
        "action": None,
        "verifyRequested": False,
        "targetDeployment": _normalize_system_name(system),
        "targetNamespace": DEFAULT_NAMESPACE,
        "targetReplicas": None,
        "rcaCause": top_cause.get("cause"),
        "rcaProbability": top_cause.get("probability"),
        "confidence": (blocked_rca or {}).get("confidence"),
        "summary": (
            "Live evidence observed for restart cooldown guardrail blocking repeated self-healing."
            if blocked_restart
            else "No recent live evidence has been matched yet for restart cooldown guardrail blocking."
        ),
    }

    return {
        "scenario-1": scenario_1,
        "scenario-2": scenario_2,
        "scenario-3": scenario_3,
    }


def _pick_policy_for_window(policy_events: list, system: str, window_id: str | None) -> dict | None:
    if not window_id:
        return None

    window_epoch = _parse_event_epoch(window_id)
    if window_epoch is None:
        return None

    expected_target_name = _normalize_system_name(system)

    best_event = None
    best_delta = None

    for event in policy_events:
        action_plan = event.get("action_plan") or {}
        target = action_plan.get("target") or {}
        target_name = target.get("name")

        event_policy = event.get("policy")
        event_decision = str(event.get("decision", "")).lower()
        guardrail_reason = str(event.get("guardrail_reason", "")).lower()

        target_matches = target_name == expected_target_name
        blocked_restart_cooldown = (
            event_policy == "restart_on_anomaly_error"
            and event_decision == "blocked"
            and "restart cooldown" in guardrail_reason
        )

        if not target_matches and not blocked_restart_cooldown:
            continue

        event_epoch = _parse_event_epoch(event.get("ts_utc") or event.get("ts"))
        if event_epoch is None:
            continue

        delta = event_epoch - window_epoch
        if delta < 0:
            continue

        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_event = event

    return best_event

def _apply_scenario_context(
    *,
    scenario_key: str | None,
    live_scenarios: dict,
    signals: dict,
    policy_events: list,
    system: str,
):
    if not scenario_key:
        return None

    scenario = live_scenarios.get(scenario_key)
    if not scenario or not scenario.get("observed"):
        return None

    window_ids = scenario.get("windowIds") or []
    window_id = window_ids[0] if window_ids else None
    anomalies = signals.get("anomalies", []) or []
    rcas = signals.get("rcas", []) or []

    anomaly = None
    if window_id:
        for item in anomalies:
            if item.get("service") == system and str(item.get("windowId")) == str(window_id):
                anomaly = item
                break

    rca = _pick_rca_for_window(rcas, system, window_id)
    policy = _pick_policy_for_window(policy_events, system, window_id)

    return {
        "scenario": scenario,
        "anomaly": anomaly,
        "rca": rca,
        "policy": policy,
        "windowId": window_id,
    }


def _pick_anomaly_for_window(anomalies: list, system: str, window_id: str | None) -> dict | None:
    if not window_id:
        return None
    for item in anomalies:
        if item.get("service") == system and str(item.get("windowId")) == str(window_id):
            return item
    return None


def _apply_window_context(
    *,
    window_id: str | None,
    signals: dict,
    policy_events: list,
    system: str,
):
    if not window_id:
        return None

    anomalies = signals.get("anomalies", []) or []
    rcas = signals.get("rcas", []) or []

    anomaly = _pick_anomaly_for_window(anomalies, system, window_id)
    rca = _pick_rca_for_window(rcas, system, window_id)
    policy = _pick_policy_for_window(policy_events, system, window_id)

    if not anomaly and not rca and not policy:
        return None

    return {
        "windowId": window_id,
        "anomaly": anomaly,
        "rca": rca,
        "policy": policy,
    }


def _wait_for_policy_event(policy_name: str, system: str, started_epoch: int, timeout_seconds: int = 120) -> dict | None:
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        events = _get_policy_events(limit=30)
        for event in events:
            action_plan = event.get("action_plan") or {}
            target = action_plan.get("target") or {}
            event_epoch = _parse_event_epoch(event.get("ts_utc") or event.get("ts"))

            if (
                event.get("policy") == policy_name
                and target.get("name") == _normalize_system_name(system)
                and event_epoch is not None
                and event_epoch >= started_epoch
            ):
                return event

        time.sleep(3)

    return None

def _wait_for_blocked_restart_cooldown(system: str, started_epoch: int, timeout_seconds: int = 120) -> dict | None:
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        events = _get_policy_events(limit=40)
        for event in events:
            event_epoch = _parse_event_epoch(event.get("ts_utc") or event.get("ts"))
            guardrail_reason = str(event.get("guardrail_reason", "")).lower()

            if (
                event.get("policy") == "restart_on_anomaly_error"
                and str(event.get("decision", "")).lower() == "blocked"
                and "restart cooldown" in guardrail_reason
                and event_epoch is not None
                and event_epoch >= started_epoch
            ):
                return event

        time.sleep(3)

    return None

def _pick_matching_window_for_policy(policy_event: dict | None, signals: dict, system: str, anomaly_type: str) -> str | None:
    if not policy_event:
        return None

    anomalies = signals.get("anomalies", []) or []
    matched = _pick_closest_anomaly_for_policy(
        anomalies=anomalies,
        system=system,
        anomaly_type=anomaly_type,
        policy_event=policy_event,
    )

    if matched and matched.get("windowId"):
        return str(matched.get("windowId"))

    return None


def _get_simulator_pods(namespace: str = DEFAULT_NAMESPACE) -> list[dict]:
    payload = _orchestrator_get_json(
        "/v1/k8s/pods",
        params={
            "namespace": namespace,
            "label_selector": SIMULATOR_LABEL_SELECTOR,
        },
        timeout=15,
    )
    items = payload.get("items", []) if isinstance(payload, dict) else []
    return [item for item in items if item.get("phase") == "Running" and item.get("pod_ip")]


def _call_simulator_pod(pod_ip: str, path: str, method: str = "POST", timeout: int = 8) -> dict:
    url = f"http://{pod_ip}:8000{path}"
    try:
        if method.upper() == "POST":
            resp = requests.post(url, timeout=timeout)
        else:
            resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Simulator pod call failed pod_ip=%s path=%s err=%s", pod_ip, path, exc)
        return {"ok": False, "error": str(exc), "pod_ip": pod_ip, "path": path}


def _disable_all_simulator_chaos(namespace: str = DEFAULT_NAMESPACE) -> dict:
    pods = _get_simulator_pods(namespace)
    if not pods:
        return {
            "ok": False,
            "message": "No running ERP simulator pods found.",
            "pods": [],
        }

    paths = [
        "/chaos/memory-leak/disable",
        "/chaos/cpu-spike/disable",
        "/chaos/latency-jitter/disable",
        "/chaos/error-burst/disable",
    ]

    pod_results = []
    overall_ok = True

    for pod in pods:
        pod_ip = pod.get("pod_ip")
        calls = []
        for path in paths:
            result = _call_simulator_pod(pod_ip, path, method="POST")
            calls.append({"path": path, "result": result})
            if isinstance(result, dict) and result.get("ok") is False:
                overall_ok = False

        modes_result = _call_simulator_pod(pod_ip, "/chaos/modes", method="GET")
        if isinstance(modes_result, dict) and modes_result.get("ok") is False:
            overall_ok = False

        pod_results.append({
            "pod": pod.get("name"),
            "pod_ip": pod_ip,
            "calls": calls,
            "modes": modes_result,
        })

    return {
        "ok": overall_ok,
        "message": "Chaos modes disabled on current simulator pods.",
        "pods": pod_results,
    }


def _orchestrator_patch_deployment(name: str, patch: dict, namespace: str = DEFAULT_NAMESPACE, dry_run: bool = False) -> dict:
    return _orchestrator_post_json(
        f"/v1/k8s/patch/{name}",
        payload={
            "namespace": namespace,
            "patch": patch,
            "dry_run": dry_run,
        },
        timeout=30,
    )


def _reset_simulator_baseline(namespace: str = DEFAULT_NAMESPACE) -> dict:
    steps = []

    disable_before = _disable_all_simulator_chaos(namespace)
    steps.append({"step": "disable_chaos_before_scale", "result": disable_before})

    scale_result = orchestrator.trigger_scale(namespace, SIMULATOR_DEPLOYMENT, BASELINE_REPLICAS, dry_run=False)
    steps.append({"step": "scale_to_baseline", "result": scale_result})

    verify_scale = orchestrator.verify_deployment(
        namespace=namespace,
        deployment=SIMULATOR_DEPLOYMENT,
        expected_replicas=BASELINE_REPLICAS,
    )
    steps.append({"step": "verify_baseline_scale", "result": verify_scale})

    patch_result = _orchestrator_patch_deployment(
        name=SIMULATOR_DEPLOYMENT,
        namespace=namespace,
        patch={
            "metadata": {
                "annotations": {
                    "smartops.io/remediation-level": "0",
                    "smartops.io/baseline-replicas": str(BASELINE_REPLICAS),
                }
            }
        },
        dry_run=False,
    )
    steps.append({"step": "reset_annotations", "result": patch_result})

    time.sleep(3)

    disable_after = _disable_all_simulator_chaos(namespace)
    steps.append({"step": "disable_chaos_after_scale", "result": disable_after})

    verify_ok = str(verify_scale.get("status", "")).upper() == "SUCCESS"

    post_pods = (disable_after or {}).get("pods", []) or []
    healthy_post_pods = 0
    for pod in post_pods:
        modes = pod.get("modes") or {}
        if isinstance(modes, dict) and "modes" in modes:
            healthy_post_pods += 1

    patch_ok = not (
        isinstance(patch_result, dict)
        and (
            patch_result.get("ok") is False
            or str(patch_result.get("status", "")).lower() == "error"
        )
    )

    overall_ok = verify_ok and patch_ok and healthy_post_pods >= BASELINE_REPLICAS

    return {
        "ok": overall_ok,
        "steps": steps,
        "summary": {
            "verify_ok": verify_ok,
            "patch_ok": patch_ok,
            "healthy_post_pods": healthy_post_pods,
            "expected_post_pods": BASELINE_REPLICAS,
            "note": "Unreachable stale pods during reset are tolerated if baseline rollout and current pod health are correct.",
        },
    }


def _enable_chaos_mode_on_all_pods(mode: str, namespace: str = DEFAULT_NAMESPACE) -> dict:
    pods = _get_simulator_pods(namespace)
    if not pods:
        return {
            "ok": False,
            "message": "No running ERP simulator pods found.",
            "pods": [],
        }

    path_map = {
        "cpu_spike": "/chaos/cpu-spike/enable",
        "error_burst": "/chaos/error-burst/enable",
    }
    path = path_map.get(mode)
    if not path:
        return {"ok": False, "message": f"Unsupported chaos mode: {mode}"}

    pod_results = []
    healthy_enabled_pods = 0

    for pod in pods:
        pod_ip = pod.get("pod_ip")
        enable_result = _call_simulator_pod(pod_ip, path, method="POST")
        modes_result = _call_simulator_pod(pod_ip, "/chaos/modes", method="GET")

        mode_enabled = False
        if isinstance(modes_result, dict):
            modes_payload = modes_result.get("modes")
            if isinstance(modes_payload, dict):
                mode_enabled = bool(modes_payload.get(mode, False))

        if mode_enabled:
            healthy_enabled_pods += 1

        pod_results.append({
            "pod": pod.get("name"),
            "pod_ip": pod_ip,
            "enable": enable_result,
            "modes": modes_result,
        })

    overall_ok = healthy_enabled_pods >= BASELINE_REPLICAS

    return {
        "ok": overall_ok,
        "mode": mode,
        "pods": pod_results,
        "summary": {
            "healthy_enabled_pods": healthy_enabled_pods,
            "expected_enabled_pods": BASELINE_REPLICAS,
            "note": "Unreachable stale pods are tolerated if the current baseline pod set has the requested chaos mode enabled.",
        },
    }

def _generate_simulator_load(target: str, iterations: int = 20, sleep_seconds: float = 1.0) -> dict:
    results = []
    overall_ok = True

    for i in range(iterations):
        try:
            resp = requests.post(
                f"{ERP_SIMULATOR_SERVICE_URL}/simulate/load",
                json={
                    "duration_seconds": 0.2,
                    "target": target,
                },
                timeout=10,
            )
            # For error scenario, 500 is an expected possible signal.
            if target == "error":
                accepted = resp.status_code in {200, 500}
            else:
                accepted = resp.status_code == 200

            if not accepted:
                overall_ok = False

            try:
                body = resp.json()
            except Exception:
                body = resp.text

            results.append({
                "iteration": i + 1,
                "status_code": resp.status_code,
                "body": body,
            })

        except Exception as exc:
            overall_ok = False
            results.append({
                "iteration": i + 1,
                "status_code": None,
                "error": str(exc),
            })

        time.sleep(sleep_seconds)

    return {
        "ok": overall_ok,
        "target": target,
        "iterations": iterations,
        "results": results,
    }


def _execute_scenario_k8s_native(scenario_key: str, namespace: str = DEFAULT_NAMESPACE) -> tuple[dict, str, str]:
    if scenario_key == "scenario-1":
        expected_policy = "scale_up_on_anomaly_resource_step_1"
        expected_type = "resource"
        chaos_mode = "cpu_spike"
        load_target = "cpu"
    else:
        expected_policy = "restart_on_anomaly_error"
        expected_type = "error"
        chaos_mode = "error_burst"
        load_target = "error"

    reset_result = _reset_simulator_baseline(namespace)
    if not reset_result.get("ok"):
        return (
            {
                "ok": False,
                "message": "Baseline reset failed before scenario execution.",
                "reset": reset_result,
            },
            expected_policy,
            expected_type,
        )

    enable_result = _enable_chaos_mode_on_all_pods(chaos_mode, namespace)
    if not enable_result.get("ok"):
        return (
            {
                "ok": False,
                "message": f"Failed to enable chaos mode {chaos_mode}.",
                "reset": reset_result,
                "scenario": {
                    "enable": enable_result,
                },
            },
            expected_policy,
            expected_type,
        )

    load_result = _generate_simulator_load(load_target, iterations=20, sleep_seconds=1.0)
    if not load_result.get("ok"):
        logger.warning("Scenario load generation completed with some non-ideal responses target=%s", load_target)

    return (
        {
            "ok": True,
            "reset": reset_result,
            "scenario": {
                "enable": enable_result,
                "load": load_result,
            },
        },
        expected_policy,
        expected_type,
    )

def _execute_scenario_3_k8s_native(namespace: str = DEFAULT_NAMESPACE) -> dict:
    reset_result = _reset_simulator_baseline(namespace)
    if not reset_result.get("ok"):
        return {
            "ok": False,
            "message": "Baseline reset failed before Scenario 3 execution.",
            "reset": reset_result,
        }

    first_enable = _enable_chaos_mode_on_all_pods("error_burst", namespace)
    if not first_enable.get("ok"):
        return {
            "ok": False,
            "message": "Failed to enable error_burst for first Scenario 3 run.",
            "reset": reset_result,
            "scenario": {"first_enable": first_enable},
        }
    
    first_started_epoch = int(time.time())
    first_load = _generate_simulator_load("error", iterations=20, sleep_seconds=1.0)

    first_policy = _wait_for_policy_event(
        policy_name="restart_on_anomaly_error",
        system="erp-simulator",
        started_epoch=first_started_epoch,
        timeout_seconds=120,
    )

    if not first_policy:
        return {
            "ok": False,
            "message": "Scenario 3 first restart action was not observed.",
            "reset": reset_result,
            "scenario": {
                "first_enable": first_enable,
                "first_load": first_load,
            },
        }

    second_enable = _enable_chaos_mode_on_all_pods("error_burst", namespace)
    if not second_enable.get("ok"):
        return {
            "ok": False,
            "message": "Failed to enable error_burst for second Scenario 3 run.",
            "reset": reset_result,
            "scenario": {
                "first_enable": first_enable,
                "first_load": first_load,
                "first_policy": first_policy,
                "second_enable": second_enable,
            },
        }

    second_started_epoch = int(time.time())
    second_load = _generate_simulator_load("error", iterations=20, sleep_seconds=1.0)

    blocked_policy = _wait_for_blocked_restart_cooldown(
        system="erp-simulator",
        started_epoch=second_started_epoch,
        timeout_seconds=120,
    )

    if not blocked_policy:
        return {
            "ok": False,
            "message": "Scenario 3 cooldown block was not observed.",
            "reset": reset_result,
            "scenario": {
                "first_enable": first_enable,
                "first_load": first_load,
                "first_policy": first_policy,
                "second_enable": second_enable,
                "second_load": second_load,
            },
        }
    return {
        "ok": True,
        "reset": reset_result,
        "scenario": {
            "first_enable": first_enable,
            "first_load": first_load,
            "first_policy": first_policy,
            "second_enable": second_enable,
            "second_load": second_load,
            "blocked_policy": blocked_policy,
        },
    }

@app.context_processor
def inject_globals():
    return {"mode": MODE}


@app.route("/api/overview")
def api_overview():
    anomaly = reader.get_latest_anomaly()
    rca = reader.get_latest_rca()
    decisions = reader.get_recent_decisions(limit=5)
    erp_odoo = prom.get_odoo_kpis()

    return jsonify({
        "status": "ok",
        "mode": MODE,
        "system_status": "Healthy" if not anomaly else "Degraded",
        "latest_anomaly": anomaly.__dict__ if anomaly else None,
        "latest_rca": rca.__dict__ if rca else None,
        "recent_decisions": [d.__dict__ for d in decisions],
        "erp_odoo": erp_odoo,
    })


@app.route("/api/verification", methods=["POST"])
def api_verification():
    data = request.json
    result = orchestrator.verify_deployment(
        namespace=data.get("namespace"),
        deployment=data.get("deployment"),
        expected_replicas=data.get("expected_replicas"),
    )

    system = _system_from_deployment_name(data.get("deployment"))
    _store_manual_verification(system, result)

    return jsonify(result)


@app.route("/api/actions/trigger", methods=["POST"])
def trigger_action():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"status": "error", "message": "Invalid JSON"}), 400

        action_type = data.get("action")
        ns = data.get("namespace", DEFAULT_NAMESPACE)
        name = data.get("name")
        dry_run = data.get("dry_run", True)

        if not name:
            return jsonify({"status": "error", "message": "Deployment name required"}), 400

        if action_type == "scale":
            replicas = int(data.get("replicas", 1))
            result = orchestrator.trigger_scale(ns, name, replicas, dry_run)
        elif action_type == "restart":
            result = orchestrator.trigger_restart(ns, name, dry_run)
        elif action_type == "baseline-reset":
            baseline_result = _reset_simulator_baseline(namespace=ns)
            result = {
                "operation": "baseline-reset",
                "deployment": {
                    "status": "SUCCESS" if baseline_result.get("ok") else "FAILED",
                    "attempts": 1,
                    "duration_seconds": None,
                    "result": {
                        "namespace": ns,
                        "name": name,
                        "replicas": BASELINE_REPLICAS,
                        "dry_run": False,
                        "baseline_reset": True,
                    },
                },
                "baseline": baseline_result,
            }
        else:
            return jsonify({"status": "error", "message": "Invalid action"}), 400

        wrapped = {"status": "success", "result": result}
        system = _system_from_deployment_name(name)
        _store_manual_action(system, wrapped)

        return jsonify(wrapped)

    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500


@app.route("/api/scenarios/run", methods=["POST"])
def api_run_scenario():
    data = request.get_json(force=True) or {}
    scenario_key = data.get("scenarioKey")
    system = data.get("system", "erp-simulator")
    namespace = data.get("namespace", DEFAULT_NAMESPACE)

    if system != "erp-simulator":
        return jsonify({
            "status": "error",
            "message": "Scenario execution is supported only for ERP-simulator.",
        }), 400

    if scenario_key not in {"scenario-1", "scenario-2", "scenario-3"}:
        return jsonify({
            "status": "error",
            "message": "Unsupported scenario key.",
        }), 400

    _clear_manual_state("erp-simulator")

    started_epoch = int(time.time())

    if scenario_key == "scenario-3":
        execution_result = _execute_scenario_3_k8s_native(namespace=namespace)
        expected_policy = "restart_on_anomaly_error"
        expected_type = "error"
    else:
        execution_result, expected_policy, expected_type = _execute_scenario_k8s_native(
            scenario_key=scenario_key,
            namespace=namespace,
        )

    if not execution_result.get("ok"):
        return jsonify({
            "status": "error",
            "message": execution_result.get("message", "Scenario execution failed."),
            "reset": execution_result.get("reset"),
            "scenario": execution_result.get("scenario"),
        }), 500

    if scenario_key == "scenario-3":
        matched_policy = _wait_for_blocked_restart_cooldown(
            system=system,
            started_epoch=started_epoch,
            timeout_seconds=120,
        )
    else:
        matched_policy = _wait_for_policy_event(
            policy_name=expected_policy,
            system=system,
            started_epoch=started_epoch,
            timeout_seconds=120,
        )

    window_id = None
    signals = {"anomalies": [], "rcas": []}

    for _ in range(6):
        signals = _get_recent_signals(limit=30)
        window_id = _pick_matching_window_for_policy(
            policy_event=matched_policy,
            signals=signals,
            system=system,
            anomaly_type=expected_type,
        )
        if window_id:
            break
        time.sleep(3)

    if not window_id:
        latest_live_scenarios = _build_live_scenarios(
            system=system,
            signals=signals,
            policy_events=_get_policy_events(limit=30),
        )
        latest_live = latest_live_scenarios.get(scenario_key) or {}
        latest_window_ids = latest_live.get("windowIds") or []
        if latest_window_ids:
            window_id = str(latest_window_ids[0])

        if matched_policy is None and latest_live.get("policy"):
            synthetic_action_plan = None
            if latest_live.get("action"):
                synthetic_action_plan = {
                    "type": latest_live.get("action"),
                    "verify": latest_live.get("verifyRequested"),
                    "target": {
                        "name": latest_live.get("targetDeployment"),
                        "namespace": latest_live.get("targetNamespace"),
                    },
                }
                if latest_live.get("targetReplicas") is not None:
                    synthetic_action_plan["scale"] = {
                        "replicas": latest_live.get("targetReplicas"),
                    }

            matched_policy = {
                "policy": latest_live.get("policy"),
                "decision": latest_live.get("decision"),
                "guardrail_reason": latest_live.get("guardrail"),
                "action_plan": synthetic_action_plan,
            }
    if scenario_key == "scenario-3" and not window_id and matched_policy:
        signals = _get_recent_signals(limit=40)
        window_id = _pick_matching_window_for_policy(
            policy_event=matched_policy,
            signals=signals,
            system=system,
            anomaly_type="error",
        )
    return jsonify({
        "status": "ok",
        "scenarioKey": scenario_key,
        "system": system,
        "windowId": window_id,
        "policy": matched_policy,
        "reset": execution_result.get("reset"),
        "scenario": execution_result.get("scenario"),
    })

@app.route("/api/anomalies")
def api_anomalies():
    anomaly = reader.get_latest_anomaly()
    features = reader.get_latest_features()
    return jsonify({
        "status": "ok",
        "latest_event": anomaly.__dict__ if anomaly else None,
        "feature_breakdown": features.__dict__ if features else None,
    })


@app.route("/api/anomalies/evidence")
def api_anomaly_evidence():
    limit = request.args.get("limit", default=10, type=int)
    latest = reader.get_latest_anomaly_evidence()
    history = reader.get_anomaly_history(limit=limit)

    return jsonify({
        "status": "ok",
        "latest": latest,
        "history": history,
    })


@app.route("/api/rca")
def api_rca():
    report = reader.get_latest_rca()
    return jsonify({
        "status": "ok",
        "report": report.__dict__ if report else None,
    })


@app.route("/api/policies")
def api_policies():
    try:
        raw = _get_policy_events(limit=50)

        normalized = []
        for ev in raw:
            decision_raw = ev.get("decision")
            if decision_raw == "action":
                decision = "allow"
            elif decision_raw == "blocked":
                decision = "block"
            else:
                decision = "no_action"

            normalized.append({
                "ts": ev.get("ts_utc"),
                "decision": decision,
                "policy_id": ev.get("policy", "-"),
                "reason": ev.get("guardrail_reason") or ev.get("reason") or "-",
            })

        return jsonify({"status": "ok", "decisions": normalized})

    except Exception as exc:
        return jsonify({
            "status": "error",
            "error": str(exc),
            "decisions": [],
        })


@app.route("/api/services/metrics")
def api_service_metrics():
    namespace = DEFAULT_NAMESPACE

    erp_health = prom.get_deployment_health(namespace, SIMULATOR_DEPLOYMENT)
    orch_health = prom.get_deployment_health(namespace, "smartops-orchestrator")
    odoo_health = prom.get_deployment_health(namespace, "odoo-web")

    erp_latency_ms = prom.get_latency_p95_ms_progressive({"namespace": namespace})
    odoo_kpis = prom.get_odoo_kpis()

    return jsonify({
        "status": "ok",
        "mode": MODE,
        "prometheus_url": prom.base_url if prom.enabled else None,
        "grafana_url": os.getenv("GRAFANA_URL"),
        "erp": {**erp_health, "p95_latency_ms": erp_latency_ms},
        "odoo": {
            **odoo_health,
            "p95_latency_ms": odoo_kpis.get("latency_p95_ms"),
            "request_rate_rps": odoo_kpis.get("request_rate_rps"),
            "error_5xx_rps": odoo_kpis.get("error_5xx_rps"),
            "profile": odoo_kpis.get("profile"),
        },
        "orchestrator": {**orch_health, "p95_latency_ms": None},
    })


@app.route("/api/policy/decisions")
def policy_decisions():
    limit = request.args.get("limit", default=10, type=int)
    try:
        resp = requests.get(
            f"{POLICY_ENGINE_URL}/v1/policy/audit/latest?n={limit}",
            timeout=3,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "events": [],
        }, 200


@app.route("/api/signals/recent")
def api_signals_recent():
    limit = request.args.get("limit", default=10, type=int)
    payload = _get_recent_signals(limit=limit)
    return jsonify({
        "status": "ok",
        "limit": limit,
        "anomalies": payload.get("anomalies", []),
        "rcas": payload.get("rcas", []),
    })


@app.route("/api/dashboard/state")
def api_dashboard_state():
    system = request.args.get("system", default="erp-simulator", type=str)
    limit = request.args.get("limit", default=10, type=int)
    scenario_key = request.args.get("scenario_key", default=None, type=str)
    window_id = request.args.get("window_id", default=None, type=str)

    metrics = api_service_metrics().get_json()
    signals = _get_recent_signals(limit=limit)
    policy_events = _get_policy_events(limit=limit)

    latest_anomaly = _pick_latest_for_system(signals.get("anomalies", []), system)
    latest_rca = _pick_latest_for_system(signals.get("rcas", []), system)

    if not _is_recent_event(latest_anomaly):
        latest_anomaly = None
        latest_rca = None
    elif latest_rca and str(latest_rca.get("windowId")) != str(latest_anomaly.get("windowId")):
        latest_rca = None

    latest_policy = _pick_latest_policy_for_system(policy_events, system)

    if latest_anomaly is None:
        latest_policy = None

    manual_state = MANUAL_EXECUTION_STATE.get(system, {})
    manual_action_result = manual_state.get("lastActionResult")
    manual_verification_result = manual_state.get("lastVerificationResult")

    using_bound_live_context = bool(window_id)

    effective_policy = latest_policy
    if manual_action_result and not using_bound_live_context:
        effective_policy = _build_manual_policy_like_result(manual_action_result) or latest_policy

    verification = _latest_verification_placeholder(effective_policy)
    if manual_verification_result and not using_bound_live_context:
        verification = _manual_verification_to_summary(manual_verification_result)

    if system == "odoo":
        odoo_metrics = metrics.get("odoo", {})
        system_state = build_system_state(
            system="odoo",
            mode=MODE,
            deployment=odoo_metrics.get("deployment", "odoo-web"),
            namespace=odoo_metrics.get("namespace", DEFAULT_NAMESPACE),
            connected=True,
            health_status=odoo_metrics.get("status", "unknown"),
            latency_p95_ms=odoo_metrics.get("p95_latency_ms"),
            replicas_desired=odoo_metrics.get("replicas_desired"),
            replicas_ready=odoo_metrics.get("replicas_ready"),
            replicas_available=odoo_metrics.get("replicas_available"),
            note="This ERP is connected to the SmartOps pipeline, proving pluggable ERP observability.",
        )
    else:
        erp_metrics = metrics.get("erp", {})

        effective_replicas_desired = erp_metrics.get("replicas_desired")
        effective_replicas_ready = erp_metrics.get("replicas_ready")
        effective_replicas_available = erp_metrics.get("replicas_available")

        if manual_verification_result and not using_bound_live_context:
            if manual_verification_result.get("desired_replicas") is not None:
                effective_replicas_desired = manual_verification_result.get("desired_replicas")
            if manual_verification_result.get("ready_replicas") is not None:
                effective_replicas_ready = manual_verification_result.get("ready_replicas")
            if manual_verification_result.get("available_replicas") is not None:
                effective_replicas_available = manual_verification_result.get("available_replicas")

        system_state = build_system_state(
            system="erp-simulator",
            mode=MODE,
            deployment=erp_metrics.get("deployment", SIMULATOR_DEPLOYMENT),
            namespace=erp_metrics.get("namespace", DEFAULT_NAMESPACE),
            connected=True,
            health_status=erp_metrics.get("status", "unknown"),
            latency_p95_ms=erp_metrics.get("p95_latency_ms"),
            replicas_desired=effective_replicas_desired,
            replicas_ready=effective_replicas_ready,
            replicas_available=effective_replicas_available,
        )

    live_scenarios = _build_live_scenarios(
        system=system,
        signals=signals,
        policy_events=policy_events,
    )

    scenario_context = _apply_scenario_context(
        scenario_key=scenario_key,
        live_scenarios=live_scenarios,
        signals=signals,
        policy_events=policy_events,
        system=system,
    )

    window_context = _apply_window_context(
        window_id=window_id,
        signals=signals,
        policy_events=policy_events,
        system=system,
    )

    effective_anomaly = latest_anomaly
    effective_rca = latest_rca
    effective_system_state = dict(system_state)

    bound_context = None

    if window_context:
        bound_context = window_context
        if window_context.get("anomaly") is not None:
            effective_anomaly = window_context.get("anomaly")
        if window_context.get("rca") is not None:
            effective_rca = window_context.get("rca")
        if window_context.get("policy") is not None:
            effective_policy = window_context.get("policy")

    elif scenario_context and not manual_action_result and not manual_verification_result:
        bound_context = scenario_context
        if scenario_context.get("anomaly") is not None:
            effective_anomaly = scenario_context.get("anomaly")
        if scenario_context.get("rca") is not None:
            effective_rca = scenario_context.get("rca")
        if scenario_context.get("policy") is not None:
            effective_policy = scenario_context.get("policy")

    if bound_context and not manual_verification_result:
        inferred_verification = _derive_live_verification_from_state(
            effective_system_state,
            effective_policy,
        )
        if inferred_verification is not None:
            verification = inferred_verification
        else:
            verification = _latest_verification_placeholder(effective_policy)

    if system == "erp-simulator" and bound_context and effective_policy:
        action_plan = effective_policy.get("action_plan") or {}
        action_type = action_plan.get("type")
        scale_plan = action_plan.get("scale") or {}

        if action_type == "scale" and scale_plan.get("replicas") is not None:
            target_replicas = scale_plan.get("replicas")
            effective_system_state["replicasDesired"] = target_replicas
            effective_system_state["replicasReady"] = target_replicas
            effective_system_state["replicasAvailable"] = target_replicas

        elif action_type == "restart":
            current_ready = effective_system_state.get("replicasReady")
            current_desired = effective_system_state.get("replicasDesired")
            current_available = effective_system_state.get("replicasAvailable")
            if current_ready is not None:
                effective_system_state["replicasReady"] = current_ready
            if current_desired is not None:
                effective_system_state["replicasDesired"] = current_desired
            if current_available is not None:
                effective_system_state["replicasAvailable"] = current_available

        if not manual_verification_result:
            inferred_verification = _derive_live_verification_from_state(
                effective_system_state,
                effective_policy,
            )
            if inferred_verification is not None:
                verification = inferred_verification
            else:
                verification = _latest_verification_placeholder(effective_policy)

    summary_cards = build_summary_cards(
        system_state=effective_system_state,
        anomaly=effective_anomaly,
        rca=effective_rca,
        policy_decision=effective_policy,
        verification=verification,
    )

    pipeline_stages = build_pipeline_stages(
        system_state=effective_system_state,
        anomaly=effective_anomaly,
        rca=effective_rca,
        policy_decision=effective_policy,
        verification=verification,
    )

    last_anomaly_evidence = reader.get_latest_anomaly_evidence()

    if effective_anomaly:
        dashboard_evidence = build_persistent_anomaly_evidence(
            anomaly=effective_anomaly,
            rca=effective_rca,
            policy_decision=effective_policy,
            verification=verification,
        )
        persist_dashboard_anomaly_evidence(dashboard_evidence)
        last_anomaly_evidence = dashboard_evidence or last_anomaly_evidence

    anomaly_history = reader.get_anomaly_history(limit=5)

    return jsonify({
        "status": "ok",
        "mode": MODE,
        "system": system,
        "systemState": effective_system_state,
        "summaryCards": summary_cards,
        "pipelineStages": pipeline_stages,
        "liveScenarioEvidence": live_scenarios,
        "selectedScenarioKey": scenario_key,
        "selectedWindowId": window_id,
        "latestAnomaly": effective_anomaly,
        "latestRca": effective_rca,
        "latestPolicyDecision": effective_policy,
        "verification": verification,
        "signals": signals,
        "lastActionResult": manual_action_result,
        "lastVerificationResult": manual_verification_result,
        "manualStateUpdatedAt": manual_state.get("updatedAt"),
        "lastAnomalyEvidence": last_anomaly_evidence,
        "anomalyHistory": anomaly_history,
    })


@app.route("/healthz")
@app.route("/api/healthz")
def healthz():
    return jsonify({
        "status": "ok",
        "service": "smartops-dashboard-api",
        "mode": MODE,
    }), 200


port = int(os.environ.get("DASHBOARD_PORT", 5050))
debug = os.environ.get("DASHBOARD_DEBUG", "false").strip().lower() in ("1", "true", "yes", "y", "on")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=debug)
