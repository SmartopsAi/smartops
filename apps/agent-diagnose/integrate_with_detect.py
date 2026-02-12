import time
import os
import requests
from datetime import datetime

from rca_engine import RCAEngine
from correlation.correlator import Correlator
from correlation.signal_linker import SignalLinker
from decision.rca_decider import RCADecider
from reporter.rca_reporter import RCAReporter

# ============================================================
# CONFIG
# ============================================================

# Kubernetes service names (override via env if running local)
ERP_URL = os.getenv("ERP_URL", "http://smartops-erp-simulator:9000")
ORCH_URL = os.getenv("ORCH_URL", "http://smartops-orchestrator:8000")

last_sent_anomaly = None  # Prevent duplicate RCA spam


# -------------------------------------------------
# 🔹 Utility: Detect active anomaly from ERP
# -------------------------------------------------
def get_active_anomaly():
    """
    Reads active chaos mode from ERP simulator
    This is the SINGLE SOURCE OF TRUTH
    """
    try:
        res = requests.get(f"{ERP_URL}/chaos/modes", timeout=3)
        modes = res.json().get("modes", {})
        for mode, active in modes.items():
            if active:
                return mode
        return "normal"
    except Exception as e:
        print("[WARN] Failed to read chaos modes:", e)
        return "unknown"


# -------------------------------------------------
# 🔹 Utility: Generate metric evidence dynamically
# -------------------------------------------------
def infer_metric_events(anomaly_type):
    mapping = {
        "cpu_spike": ["cpu_burn_ms ↑", "request_count ↑"],
        "latency_jitter": ["latency_jitter_ms ↑", "request_latency ↑"],
        "memory_leak": ["memory_leak_bytes ↑"],
        "error_burst": ["error_rate ↑"]
    }
    return mapping.get(anomaly_type, [])


# -------------------------------------------------
# 🔹 Send RCA signal to Orchestrator
# -------------------------------------------------
def send_rca_signal(report):
    try:
        payload = {
            "windowId": report["anomaly_id"],
            "service": report["root_cause"]["component"] or "erp-simulator",
            "confidence": report["confidence"],
            "rankedCauses": [
                {
                    "svc": report["root_cause"]["component"] or "erp-simulator",
                    "cause": report["root_cause"]["type"],
                    "p": report["confidence"],
                }
            ],
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
    global last_sent_anomaly

    anomaly_type = get_active_anomaly()

    if anomaly_type in ["normal", "unknown"]:
        print("[INFO] No active anomaly — RCA skipped")
        last_sent_anomaly = None
        return

    # Prevent duplicate RCA for same anomaly mode
    if anomaly_type == last_sent_anomaly:
        return

    print(f"[INFO] Running RCA for anomaly: {anomaly_type}")

    metric_events = infer_metric_events(anomaly_type)

    # Example logs & traces
    log_events = [
        {
            "severity": "ERROR",
            "message": "TimeoutError in OrderService"
        }
    ]

    trace_events = [
        {
            "from": "OrderService",
            "to": "DatabaseService",
            "latency": 850
        }
    ]

    # ---------------- Stage 3.4 ----------------
    correlator = Correlator()
    correlated = correlator.correlate(
        metric_events, log_events, trace_events
    )

    linker = SignalLinker()
    failure_type = linker.infer_failure_type(correlated)

    # ---------------- Stage 3.5 ----------------
    decider = RCADecider()
    root_cause, confidence = decider.decide(
        correlated, failure_type
    )

    # ---------------- Stage 3.6 ----------------
    reporter = RCAReporter()
    anomaly_id = f"A-{int(time.time())}"

    report = reporter.generate(
        anomaly_id=anomaly_id,
        anomaly_type=anomaly_type,
        root_cause=root_cause,
        evidence=correlated,
        confidence=confidence
    )

    reporter.print_report(report)

    # ---------------- Save JSON locally ----------------
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
    output_path = os.path.join(project_root, "data", "runtime", "latest_rca.json")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    print(f"[INFO] Saving report to: {output_path}")
    reporter.save_json(report, output_path)

    # ---------------- Send to Orchestrator ----------------
    send_rca_signal(report)

    last_sent_anomaly = anomaly_type


# -------------------------------------------------
# 🔹 ENTRY POINT
# -------------------------------------------------
if __name__ == "__main__":
    print("[INFO] Agent Diagnose started")
    print(f"[INFO] ERP_URL={ERP_URL}")
    print(f"[INFO] ORCH_URL={ORCH_URL}")

    while True:
        run_rca()
        time.sleep(10)
