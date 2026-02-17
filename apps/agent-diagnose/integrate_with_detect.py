import time
import os
import requests
from typing import Optional, List, Dict, Any

from rca_engine import RCAEngine
from correlation.correlator import Correlator
from correlation.signal_linker import SignalLinker
from decision.rca_decider import RCADecider
from reporter.rca_reporter import RCAReporter

# ============================================================
# CONFIG
# ============================================================

# IMPORTANT:
# Your cluster shows orchestrator on :8001 (from your curl tests)
# Keep env overrides, but make sane defaults match k8s service.
ERP_URL = os.getenv("ERP_URL", "http://smartops-erp-simulator:8000").rstrip("/")
ORCH_URL = os.getenv("ORCH_URL", "http://smartops-orchestrator:8001").rstrip("/")

TARGET_SERVICE = os.getenv("TARGET_SERVICE", "erp-simulator")
RECENT_LIMIT = int(os.getenv("RECENT_LIMIT", "50"))
POLL_SECONDS = int(os.getenv("DIAGNOSE_POLL_SECONDS", "10"))

# Prevent duplicate RCA spam for the same anomaly window
last_processed_window_id: Optional[str] = None


# -------------------------------------------------
# 🔹 Utility: Fetch recent signals from Orchestrator (event bus)
# -------------------------------------------------
def get_recent_payload(limit: int = RECENT_LIMIT) -> Dict[str, Any]:
    """
    Reads recent signals from Orchestrator.

    ACTUAL response shape (based on your /v1/signals/recent output):
      {
        "limit": <int>,
        "anomalies": [ {windowId, service, isAnomaly, score, type, ...}, ... ],
        "rcas":      [ {windowId, service, rankedCauses, confidence, ...}, ... ]
      }
    """
    try:
        res = requests.get(
            f"{ORCH_URL}/v1/signals/recent",
            params={"limit": limit},
            timeout=3,
        )
        res.raise_for_status()
        data = res.json()
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as e:
        print("[WARN] Failed to fetch recent payload from orchestrator:", e)
        return {}


def get_recent_anomalies(limit: int = RECENT_LIMIT) -> List[Dict[str, Any]]:
    data = get_recent_payload(limit=limit)
    anomalies = data.get("anomalies", [])
    return anomalies if isinstance(anomalies, list) else []


def get_latest_anomaly_for_service(service: str) -> Optional[Dict[str, Any]]:
    """
    Returns the latest anomaly signal for the given service, if available.
    We scan from newest to oldest to avoid depending on ordering.
    """
    anomalies = get_recent_anomalies()

    # scan backwards: most recent first
    for a in reversed(anomalies):
        try:
            if a.get("service") != service:
                continue
            # Only use signals that are actually anomalies
            if bool(a.get("isAnomaly", False)) is not True:
                continue
            return a
        except Exception:
            continue

    return None


# -------------------------------------------------
# 🔹 Utility: Generate metric evidence dynamically
# -------------------------------------------------
def infer_metric_events(anomaly_type: str):
    mapping = {
        "cpu_spike": ["cpu_burn_ms ↑", "request_count ↑"],
        "latency_jitter": ["latency_jitter_ms ↑", "request_latency ↑"],
        "memory_leak": ["memory_leak_bytes ↑"],
        "error_burst": ["error_rate ↑"],
        # Newer normalized types coming from orchestrator enum:
        "resource": ["cpu_burn_ms ↑", "memory_bytes ↑"],
        "latency": ["request_latency ↑"],
        "error": ["error_rate ↑"],
        "other": [],
    }
    return mapping.get(str(anomaly_type), [])


# -------------------------------------------------
# 🔹 Send RCA signal to Orchestrator
# -------------------------------------------------
def send_rca_signal(report: dict):
    try:
        payload = {
            "windowId": report["anomaly_id"],  # correlate to anomaly windowId
            "service": TARGET_SERVICE,
            "confidence": report["confidence"],
            "rankedCauses": [
                {
                    "svc": report["root_cause"].get("component") or TARGET_SERVICE,
                    "cause": report["root_cause"].get("type"),
                    "probability": report["confidence"],
                }
            ],
            "explanation": report.get("explanation"),
            "modelVersion": report.get("model_version"),
            "metadata": report.get("metadata", {}),
        }

        response = requests.post(
            f"{ORCH_URL}/v1/signals/rca",
            json=payload,
            timeout=3,
        )

        if response.status_code < 300:
            print("[INFO] RCA signal sent to orchestrator")
        else:
            print("[WARN] Orchestrator rejected RCA:", response.text)

    except Exception as e:
        print("[WARN] Failed to send RCA signal:", e)


# -------------------------------------------------
# 🔹 MAIN RCA PIPELINE (Stage 3.4 → 3.6)
# -------------------------------------------------
def run_rca():
    global last_processed_window_id

    anomaly = get_latest_anomaly_for_service(TARGET_SERVICE)

    if not anomaly:
        print("[INFO] No recent anomaly for service — RCA skipped")
        return

    # Orchestrator AnomalySignal schema uses: windowId, isAnomaly, score, type
    window_id = anomaly.get("windowId")
    anomaly_type = anomaly.get("type", "other")  # latency|error|resource|other
    score = anomaly.get("score", None)

    if not window_id:
        # Rare, but protects against malformed signals
        print("[WARN] Anomaly missing windowId — RCA skipped")
        return

    # prevent duplicate RCA for same anomaly window
    if window_id == last_processed_window_id:
        return

    print(f"[INFO] Running RCA for anomaly: type={anomaly_type} windowId={window_id} score={score}")

    metric_events = infer_metric_events(str(anomaly_type))

    # Example logs & traces (keep as-is; you can later wire real sources)
    log_events = [{"severity": "ERROR", "message": "TimeoutError in OrderService"}]
    trace_events = [{"from": "OrderService", "to": "DatabaseService", "latency": 850}]

    # ---------------- Stage 3.4 ----------------
    correlator = Correlator()
    correlated = correlator.correlate(metric_events, log_events, trace_events)

    linker = SignalLinker()
    failure_type = linker.infer_failure_type(correlated)

    # ---------------- Stage 3.5 ----------------
    decider = RCADecider()
    root_cause, confidence = decider.decide(correlated, failure_type)

    # ---------------- Stage 3.6 ----------------
    reporter = RCAReporter()

    # IMPORTANT:
    # Use the SAME windowId as the anomaly so orchestrator can correlate.
    report = reporter.generate(
        anomaly_id=window_id,
        anomaly_type=str(anomaly_type),
        root_cause=root_cause,
        evidence=correlated,
        confidence=confidence
    )

    reporter.print_report(report)

    # ---------------- Save JSON locally ----------------
    # NOTE: In containers, this path may not be persisted; kept for parity.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    output_path = os.path.join(project_root, "data", "runtime", "latest_rca.json")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    print(f"[INFO] Saving report to: {output_path}")
    reporter.save_json(report, output_path)

    # ---------------- Send to Orchestrator ----------------
    send_rca_signal(report)

    last_processed_window_id = window_id


# -------------------------------------------------
# 🔹 ENTRY POINT
# -------------------------------------------------
if __name__ == "__main__":
    print("[INFO] Agent Diagnose started")
    print(f"[INFO] ERP_URL={ERP_URL} (unused in HTTP-bus mode)")
    print(f"[INFO] ORCH_URL={ORCH_URL}")
    print(f"[INFO] TARGET_SERVICE={TARGET_SERVICE}")
    print(f"[INFO] POLL_SECONDS={POLL_SECONDS}")

    while True:
        run_rca()
        time.sleep(POLL_SECONDS)
