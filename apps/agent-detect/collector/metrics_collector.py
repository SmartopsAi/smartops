import os
import time
import requests

from .prom_parser import parse_prometheus_text
from .metric_map import (
    SIMULATOR_PROFILE_METRICS,
    ODOO_PROFILE_METRICS,
)

# ================================
# Configuration
# ================================
PROFILE = os.getenv("PROFILE", "simulator")  # simulator | odoo

SIMULATOR_METRICS_URL = "http://localhost:9000/metrics"
PROMETHEUS_API = "http://localhost/prometheus/api/v1/query"

POLL_INTERVAL = 5  # seconds


# ================================
# Simulator path (existing)
# ================================
def normalize_simulator_metrics(raw_metrics: dict) -> dict:
    normalized = {}

    for prom_name, value in raw_metrics.items():
        if prom_name in SIMULATOR_PROFILE_METRICS:
            normalized[SIMULATOR_PROFILE_METRICS[prom_name]] = value

    return normalized


def collect_simulator_metrics():
    response = requests.get(SIMULATOR_METRICS_URL, timeout=3)
    response.raise_for_status()

    raw = parse_prometheus_text(response.text)
    return normalize_simulator_metrics(raw)


# ================================
# Odoo / ERP path (PromQL-based)
# ================================
def collect_odoo_metrics():
    results = {}

    for semantic_name, spec in ODOO_PROFILE_METRICS.items():
        if spec.get("type") != "promql":
            continue

        query = spec["query"]

        resp = requests.get(
            PROMETHEUS_API,
            params={"query": query},
            timeout=5,
        )
        resp.raise_for_status()

        data = resp.json()["data"]["result"]

        if not data:
            results[semantic_name] = 0.0
        else:
            # Prometheus returns value as [timestamp, string_value]
            results[semantic_name] = float(data[0]["value"][1])

    return results


# ================================
# Unified stream
# ================================
def stream_metrics():
    """
    Generator that yields (timestamp, normalized_metrics)
    """
    print(f"[INFO] Agent Detect running in PROFILE={PROFILE}")

    while True:
        try:
            if PROFILE == "odoo":
                normalized = collect_odoo_metrics()
            else:
                normalized = collect_simulator_metrics()

            yield time.time(), normalized

        except Exception as e:
            print(f"[WARN] Metrics fetch failed: {e}")

        time.sleep(POLL_INTERVAL)
