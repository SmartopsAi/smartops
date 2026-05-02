import os
import time
import json
import requests
from pathlib import Path

from collector.metrics_collector import stream_metrics
from features.windowing import SlidingWindow
from features.feature_engineering import build_feature_vector
from live_detect import LiveAnomalyDetector

# ===================================
# CONFIGURATION
# ===================================
WINDOW_SECONDS = int(os.getenv("WINDOW_SECONDS", "30"))
WARMUP_WINDOWS = int(os.getenv("WARMUP_WINDOWS", "1"))
RECOVERY_WINDOWS = int(os.getenv("RECOVERY_WINDOWS", "2"))
FAST_WARNING_ENABLED = os.getenv("FAST_WARNING_ENABLED", "1") == "1"
SIM_USE_GROUND_TRUTH = os.getenv("SIM_USE_GROUND_TRUTH", "0") == "1"

PROFILE = os.getenv("PROFILE", "simulator")  # simulator | odoo

# Orchestrator endpoint (K8s default service name)
ORCH_URL = os.getenv("ORCH_URL", "http://smartops-orchestrator:8001")

# ===================================
# INIT
# ===================================
window_60s = SlidingWindow(window_size_seconds=WINDOW_SECONDS)
detector = LiveAnomalyDetector()

RUNTIME_DIR = Path(os.getenv("SMARTOPS_RUNTIME_DIR", "/app/data/runtime"))
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

def append_jsonl(path: Path, event: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def persist_last_anomaly_evidence(
    *,
    service: str,
    anomaly_type: str,
    anomaly_final: bool,
    risk: str,
    features: dict,
    result: dict,
    metrics: dict,
):
    """
    Preserve the latest anomaly evidence even after live state becomes normal.
    This supports viva/demo explanation after auto-healing.
    """
    if not anomaly_final:
        return

    now = time.time()
    event = {
        "eventId": f"A-{int(now)}",
        "timestamp": now,
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "service": service,
        "type": anomaly_type,
        "severity": "CRITICAL" if risk == "HIGH" else "WARNING",
        "risk": risk,
        "score": 0.9,
        "source": "agent-detect",
        "profile": PROFILE,
        "detection": {
            "statistical": bool(result.get("statistical", False)),
            "isolation_forest": bool(result.get("isolation_forest", False)),
            "final": bool(result.get("final", False)),
        },
        "features": features,
        "metrics": metrics,
        "status": "RECORDED_FOR_EVIDENCE",
    }

    with open(RUNTIME_DIR / "latest_anomaly_evidence.json", "w", encoding="utf-8") as f:
        json.dump(event, f, indent=2)

    append_jsonl(RUNTIME_DIR / "anomaly_history.jsonl", event)


window_count = 0
clean_counter = 0
anomaly_state = False
last_sent_state = False
last_sent_window_key = None  # Track last emitted anomaly window/type

# ===================================
# HELPER: Send anomaly to orchestrator
# ===================================
def send_anomaly_signal(service: str, anomaly_type: str, anomaly_final: bool, risk: str):
    try:
        payload = {
            "windowId": str(int(time.time())),
            "service": service,
            "type": anomaly_type,  # resource | error
            "score": 0.9 if anomaly_final else 0.1,
            "isAnomaly": anomaly_final,
            "metadata": {
                "source": "agent-detect",
                "profile": PROFILE,
                "risk": risk,
            },
        }

        response = requests.post(
            f"{ORCH_URL}/v1/signals/anomaly",
            json=payload,
            timeout=3,
        )

        if response.status_code < 300:
            print("[INFO] Anomaly signal sent to orchestrator", payload)
        else:
            print("[WARN] Orchestrator rejected signal:", response.text)

    except Exception as e:
        print("[WARN] Failed to send anomaly signal:", e)


# ===================================
# MAIN LOOP
# ===================================
def main():
    global window_count, clean_counter, anomaly_state, last_sent_state, last_sent_window_key

    print("[INFO] Agent Detect started (LIVE)")
    print(f"[INFO] Running PROFILE={PROFILE}")
    print(f"[INFO] Orchestrator URL={ORCH_URL}")

    for ts, metrics in stream_metrics():
        window_60s.add(ts, metrics)

        if not window_60s.is_ready():
            continue

        window_count += 1

        # -------------------------------
        # Feature Engineering
        # -------------------------------
        features = build_feature_vector(window_60s.values())
        if not features:
            continue

        # -------------------------------
        # Fast-path warning
        # -------------------------------
        # This gives earlier warning for mission-critical cases before the
        # full anomaly state is confirmed by the heavier model path.
        fast_warning = False
        fast_warning_reasons = []

        if FAST_WARNING_ENABLED:
            try:
                error_max = float(features.get("error_count_max", 0.0) or 0.0)
                modes_max = float(features.get("modes_enabled_max", 0.0) or 0.0)
                cpu_spike = float(features.get("cpu_burn_ms_spike", 0.0) or 0.0)
                cpu_max = float(features.get("cpu_burn_ms_max", 0.0) or 0.0)
                latency_spike = float(features.get("latency_jitter_ms_spike", 0.0) or 0.0)
                latency_max = float(features.get("latency_jitter_ms_max", 0.0) or 0.0)

                if error_max > 0:
                    fast_warning = True
                    fast_warning_reasons.append("error_count increased")

                if modes_max > 0 and (cpu_spike > 0 or cpu_max > 0):
                    fast_warning = True
                    fast_warning_reasons.append("resource chaos signal detected")

                if latency_spike > 0 or latency_max > 0:
                    fast_warning = True
                    fast_warning_reasons.append("latency jitter increased")

            except Exception as exc:
                print(f"[WARN] Fast warning evaluation failed: {exc}")

        # -------------------------------
        # Detection Models
        # -------------------------------
        result = detector.detect(features)

        stat_result = bool(result.get("statistical", False))
        iso_result = bool(result.get("isolation_forest", False))

        # -------------------------------
        # Ground truth (SIMULATOR ONLY)
        # -------------------------------
        if PROFILE == "simulator":
            modes_enabled = float(metrics.get("modes_enabled", 0) or 0)
            error_count = float(metrics.get("error_count", 0.0) or 0.0)

            error_ground_truth = error_count > 0.0
            resource_ground_truth = modes_enabled > 0 and not error_ground_truth
            ground_truth_active = error_ground_truth or resource_ground_truth
        else:
            error_ground_truth = False
            resource_ground_truth = False
            ground_truth_active = False

        # -------------------------------
        # DECISION GATING
        # -------------------------------
        if PROFILE == "odoo":
            no_ep = float(metrics.get("odoo_no_endpoint", 0.0))
            raw_anomaly = (no_ep >= 1.0)
        else:
            # simulator
            if SIM_USE_GROUND_TRUTH:
                raw_anomaly = fast_warning or error_ground_truth or resource_ground_truth or iso_result or stat_result
            else:
                raw_anomaly = fast_warning or iso_result or (stat_result and ground_truth_active)
        # -------------------------------
        # WARM-UP PROTECTION
        # -------------------------------
        if window_count <= WARMUP_WINDOWS:
            anomaly_state = False
            clean_counter = 0
            anomaly_final = False
            risk = "LOW"

        else:
            if anomaly_state:
                if raw_anomaly:
                    clean_counter = 0
                else:
                    clean_counter += 1

                if clean_counter >= RECOVERY_WINDOWS:
                    anomaly_state = False
                    clean_counter = 0
            else:
                if raw_anomaly:
                    anomaly_state = True
                    clean_counter = 0

            anomaly_final = anomaly_state

            if anomaly_state:
                risk = "HIGH"
            elif clean_counter > 0:
                risk = "MEDIUM"
            else:
                risk = "LOW"

        # -------------------------------
        # CONSOLE OUTPUT
        # -------------------------------
        print("\n--- LIVE DETECTION ---")
        print(f"Time: {time.strftime('%H:%M:%S')}")
        print(f"Profile: {PROFILE}")
        print(f"Anomaly Detected: {anomaly_final}")
        print(f"  Statistical: {stat_result}")
        print(f"  IsolationForest: {iso_result}")
        print(f"  FastWarning: {fast_warning} {fast_warning_reasons}")
        print(f"  RecoveryWindows: {clean_counter}/{RECOVERY_WINDOWS}")

        # -------------------------------
        # SAVE: LIVE DETECTION STATUS
        # -------------------------------
        with open(RUNTIME_DIR / "latest_detection.json", "w") as f:
            json.dump({
                "timestamp": time.time(),
                "profile": PROFILE,
                "anomaly": anomaly_final,
                "statistical": stat_result,
                "isolation_forest": iso_result,
                "fast_warning": fast_warning,
                "fast_warning_reasons": fast_warning_reasons,
                "window_seconds": WINDOW_SECONDS,
                "warmup_windows": WARMUP_WINDOWS,
                "recovering": anomaly_state and not raw_anomaly,
                "recovery_windows": clean_counter,
                "required_recovery_windows": RECOVERY_WINDOWS
            }, f, indent=2)

        # -------------------------------
        # SAVE: RISK STATUS
        # -------------------------------
        with open(RUNTIME_DIR / "latest_risk.json", "w") as f:
            json.dump({
                "risk": risk,
                "timestamp": time.time(),
                "profile": PROFILE
            }, f, indent=2)
        # -------------------------------
        # Service + type mapping (production)
        # -------------------------------
        service_name = "odoo" if PROFILE == "odoo" else "erp-simulator"

        anomaly_type = "resource"
        if PROFILE == "odoo":
            try:
                if float(metrics.get("odoo_no_endpoint", 0.0)) >= 1.0:
                    anomaly_type = "error"
            except Exception:
                pass
        else:
            try:
                if float(metrics.get("error_count", 0.0)) > 0.0:
                    anomaly_type = "error"
            except Exception:
                pass
        # -------------------------------
        # SEND TO ORCHESTRATOR
        # Emit once per anomaly window/type, not only on boolean state change.
        # This lets repeated demo scenarios generate fresh signals even if the
        # detector remains in anomaly state across adjacent windows.
        # -------------------------------
        current_window_key = (anomaly_final, anomaly_type, risk, int(time.time() // WINDOW_SECONDS))

        if anomaly_final:
            if current_window_key != last_sent_window_key:
                send_anomaly_signal(service_name, anomaly_type, anomaly_final, risk)

                persist_last_anomaly_evidence(
                    service=service_name,
                    anomaly_type=anomaly_type,
                    anomaly_final=anomaly_final,
                    risk=risk,
                    features=features,
                    result=result,
                    metrics=metrics,
                )

                last_sent_window_key = current_window_key
            last_sent_state = True
        else:
            last_sent_state = False
            last_sent_window_key = None

        time.sleep(1)


# ===================================
# ENTRY POINT
# ===================================
if __name__ == "__main__":
    main()
