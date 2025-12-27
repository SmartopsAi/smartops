from collector.metrics_collector import stream_metrics
from features.windowing import SlidingWindow
from features.feature_engineering import build_feature_vector
from live_detect import LiveAnomalyDetector

import time

window_60s = SlidingWindow(window_size_seconds=60)

FEATURE_METRICS = [
    "request_count",
    "latency_jitter_ms",
    "cpu_burn_ms",
    "memory_leak_bytes"
]

detector = LiveAnomalyDetector()

def main():
    print("[INFO] Agent Detect started (PHASE 2 – LIVE)")

    for ts, metrics in stream_metrics():
        window_60s.add(ts, metrics)

        if window_60s.is_ready():
            features = build_feature_vector(
                window_60s.values(),
                FEATURE_METRICS
            )

            if not features:
                continue

            result = detector.detect(features)

            print("\n--- LIVE DETECTION ---")
            print(f"Time: {time.strftime('%H:%M:%S')}")
            print(f"Anomaly Detected: {result['final']}")
            print(f"  Statistical: {result['statistical']}")
            print(f"  IsolationForest: {result['isolation_forest']}")
            print(f"  GroundTruth: {'ANOMALY' if metrics.get('modes_enabled',0)>0 else 'NORMAL'}")

if __name__ == "__main__":
    main()
