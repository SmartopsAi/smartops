import time
import requests
from datetime import datetime

from rca_engine import RCAEngine
from correlation.correlator import Correlator
from correlation.signal_linker import SignalLinker
from decision.rca_decider import RCADecider
from reporter.rca_reporter import RCAReporter


# -------------------------------------------------
# 🔹 Utility: Detect active anomaly from ERP
# -------------------------------------------------
def get_active_anomaly():
    """
    Reads active chaos mode from ERP simulator
    This is the SINGLE SOURCE OF TRUTH
    """
    try:
        res = requests.get("http://localhost:9000/chaos/modes", timeout=2)
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
# 🔹 MAIN RCA PIPELINE (Stage 3.4 → 3.6)
# -------------------------------------------------
def run_rca():
    anomaly_type = get_active_anomaly()

    if anomaly_type in ["normal", "unknown"]:
        print("[INFO] No active anomaly — RCA skipped")
        return

    print(f"[INFO] Running RCA for anomaly: {anomaly_type}")

    metric_events = infer_metric_events(anomaly_type)

    # Example logs & traces (Phase 3 scope)
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
    reporter.save_json(report, f"data/runtime/latest_rca.json")


# -------------------------------------------------
# 🔹 ENTRY POINT
# -------------------------------------------------
if __name__ == "__main__":
    while True:
        run_rca()
        time.sleep(10)
