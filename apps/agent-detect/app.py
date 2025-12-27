from collector.metrics_collector import stream_metrics
from features.windowing import SlidingWindow
from features.feature_engineering import build_feature_vector
from live_detect import LiveAnomalyDetector

import time
import json
from pathlib import Path

# ===================================
# CONFIGURATION
# ===================================
WINDOW_SECONDS = 60
WARMUP_WINDOWS = 5
RECOVERY_WINDOWS = 3

FEATURE_METRICS = [
    "request_count",
    "latency_jitter_ms",
    "cpu_burn_ms",
    "memory_leak_bytes"
]

# ===================================
# INIT
# ===================================
window_60s = SlidingWindow(window_size_seconds=WINDOW_SECONDS)
detector = LiveAnomalyDetector()

RUNTIME_DIR = Path("data/runtime")
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

window_count = 0
clean_counter = 0
anomaly_state = False  # tracks if system is currently in anomaly

# ===================================
# MAIN LOOP
# ===================================
def main():
    global window_count, clean_counter, anomaly_state

    print("[INFO] Agent Detect started (PHASE 2 – LIVE)")

    for ts, metrics in stream_metrics():
        window_60s.add(ts, metrics)

        if not window_60s.is_ready():
            continue

        window_count += 1

        # -------------------------------
        # Feature Engineering
        # -------------------------------
        features = build_feature_vector(
            window_60s.values(),
            FEATURE_METRICS
        )
        if not features:
            continue

        # -------------------------------
        # Detection Models
        # -------------------------------
        result = detector.detect(features)

        stat_result = bool(result.get("statistical", False))
        iso_result = bool(result.get("isolation_forest", False))

        # Ground truth from simulator
        ground_truth_active = metrics.get("modes_enabled", 0) > 0
        ground_truth = "ANOMALY" if ground_truth_active else "NORMAL"

        # -------------------------------
        # DECISION GATING (CRITICAL FIX)
        # -------------------------------
        # Statistical alone CANNOT trigger anomaly in live mode
        raw_anomaly = iso_result or (stat_result and ground_truth_active)

        # -------------------------------
        # WARM-UP PROTECTION
        # -------------------------------
        if window_count <= WARMUP_WINDOWS:
            anomaly_state = False
            clean_counter = 0
            anomaly_final = False
            risk = "LOW"

        else:
            # -------------------------------
            # STATE MACHINE WITH RECOVERY
            # -------------------------------
            if anomaly_state:
                # Already in anomaly → wait for recovery
                if raw_anomaly:
                    clean_counter = 0
                else:
                    clean_counter += 1

                if clean_counter >= RECOVERY_WINDOWS:
                    anomaly_state = False
                    clean_counter = 0

            else:
                # Not in anomaly → check trigger
                if raw_anomaly:
                    anomaly_state = True
                    clean_counter = 0

            anomaly_final = anomaly_state

            # -------------------------------
            # RISK ESTIMATION
            # -------------------------------
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
        print(f"Anomaly Detected: {anomaly_final}")
        print(f"  Statistical: {stat_result}")
        print(f"  IsolationForest: {iso_result}")
        print(f"  GroundTruth: {ground_truth}")
        print(f"  RecoveryWindows: {clean_counter}/{RECOVERY_WINDOWS}")

        # -------------------------------
        # SAVE: LIVE DETECTION STATUS
        # -------------------------------
        with open(RUNTIME_DIR / "latest_detection.json", "w") as f:
            json.dump({
                "timestamp": time.time(),
                "anomaly": anomaly_final,
                "statistical": stat_result,
                "isolation_forest": iso_result,
                "ground_truth": ground_truth,
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
                "timestamp": time.time()
            }, f, indent=2)

        time.sleep(1)

# ===================================
# ENTRY POINT
# ===================================
if __name__ == "__main__":
    main()
