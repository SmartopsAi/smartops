import os
import time
import json
from pathlib import Path

from collector.metrics_collector import stream_metrics
from features.windowing import SlidingWindow
from features.feature_engineering import build_feature_vector
from live_detect import LiveAnomalyDetector

# ===================================
# CONFIGURATION
# ===================================
WINDOW_SECONDS = 60
WARMUP_WINDOWS = 5
RECOVERY_WINDOWS = 3

PROFILE = os.getenv("PROFILE", "simulator")  # simulator | odoo

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

    print("[INFO] Agent Detect started (LIVE)")
    print(f"[INFO] Running PROFILE={PROFILE}")

    for ts, metrics in stream_metrics():
        window_60s.add(ts, metrics)

        if not window_60s.is_ready():
            continue

        window_count += 1

        # -------------------------------
        # Feature Engineering (PROFILE-AWARE)
        # -------------------------------
        features = build_feature_vector(window_60s.values())
        if not features:
            continue

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
            ground_truth_active = metrics.get("modes_enabled", 0) > 0
        else:
            ground_truth_active = False  # ERP has no synthetic ground truth

        ground_truth = "ANOMALY" if ground_truth_active else "NORMAL"

        # -------------------------------
        # DECISION GATING
        # -------------------------------
        if PROFILE == "odoo":
            # ERP mode: Isolation Forest is authoritative
            raw_anomaly = iso_result
        else:
            # Simulator mode: hybrid gating
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
        print(f"Profile: {PROFILE}")
        print(f"Anomaly Detected: {anomaly_final}")
        print(f"  Statistical: {stat_result}")
        print(f"  IsolationForest: {iso_result}")
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

        time.sleep(1)

# ===================================
# ENTRY POINT
# ===================================
if __name__ == "__main__":
    main()
