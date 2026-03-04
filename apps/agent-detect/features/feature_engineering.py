import numpy as np
import json
import os
from pathlib import Path

# Single source of truth for runtime output (dashboard uses this)
RUNTIME_DIR = Path(os.getenv("SMARTOPS_RUNTIME_DIR", "/app/data/runtime"))
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

# ================================
# Profile-aware metric selection
# ================================
PROFILE = os.getenv("PROFILE", "simulator")

SIMULATOR_METRICS = [
    "memory_leak_bytes",
    "cpu_burn_ms",
    "latency_jitter_ms",
    "request_count",
    "error_count",
    "modes_enabled",
]

# Odoo metrics collected via PromQL (see collector/metric_map.py)
ODOO_METRICS = [
    "odoo_no_endpoint",   # primary production signal (ingress no-endpoint)
    # Optional future metrics (enable when request/latency series exist):
    "erp_req_rate",
    "erp_5xx_rate",
    "erp_p95_latency",
]


def extract_metric_series(window_values, metric_name):
    """
    Extract a time-series list for a single metric from window data.
    Keeps only entries that contain the key (avoid artificial zeros).
    """
    return [
        entry.get(metric_name, 0.0)
        for entry in window_values
        if metric_name in entry
    ]


def compute_features(series):
    """
    Compute statistical & temporal features from a numeric series.
    """
    if len(series) < 2:
        return None

    arr = np.array(series, dtype=float)

    mean = float(np.mean(arr))
    std = float(np.std(arr))
    minimum = float(np.min(arr))
    maximum = float(np.max(arr))

    # Trend (simple slope)
    slope = float(arr[-1] - arr[0])

    # Spike detection (max deviation from mean)
    spike = float(np.max(np.abs(arr - mean)))

    return {
        "mean": mean,
        "std": std,
        "min": minimum,
        "max": maximum,
        "slope": slope,
        "spike": spike,
    }


def build_feature_vector(window_values):
    """
    Build full feature vector for selected metrics.
    Also saves latest feature vector for dashboard & prediction preview.
    """
    metrics = ODOO_METRICS if PROFILE == "odoo" else SIMULATOR_METRICS

    feature_vector = {}

    for metric in metrics:
        series = extract_metric_series(window_values, metric)
        features = compute_features(series)

        if not features:
            continue

        for key, value in features.items():
            feature_vector[f"{metric}_{key}"] = value

    # -------------------------------
    # SAVE latest features (dashboard & prediction preview)
    # -------------------------------
    if feature_vector:
        with open(RUNTIME_DIR / "latest_features.json", "w") as f:
            json.dump(feature_vector, f, indent=2)

    return feature_vector