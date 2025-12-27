from collector.metrics_collector import stream_metrics
from features.windowing import SlidingWindow
from features.feature_engineering import build_feature_vector
from dataset.dataset_writer import DatasetWriter

import time

# Windows
window_60s = SlidingWindow(window_size_seconds=60)

# Feature metrics
FEATURE_METRICS = [
    "request_count",
    "latency_jitter_ms",
    "cpu_burn_ms",
    "memory_leak_bytes"
]

dataset_writer = DatasetWriter()

def main():
    print("[INFO] Agent Detect started (Stage 1 – Dataset Builder)")

    for ts, metrics in stream_metrics():
        window_60s.add(ts, metrics)

        if window_60s.is_ready():
            window_values = window_60s.values()

            features = build_feature_vector(
                window_values,
                FEATURE_METRICS
            )

            if features:
                # Automatic label
                label = 1 if metrics.get("modes_enabled", 0) > 0 else 0

                dataset_writer.write(ts, features, label)

                print("\n[DATASET WRITE]")
                print(f"Label: {label}")
                print(f"Features written: {len(features)}")

if __name__ == "__main__":
    main()
