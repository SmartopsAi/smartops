import time
import requests

from .prom_parser import parse_prometheus_text
from .metric_map import METRIC_MAP

METRICS_URL = "http://localhost:9000/metrics"
POLL_INTERVAL = 5  # seconds

def normalize_metrics(raw_metrics: dict) -> dict:
    normalized = {}

    for prom_name, value in raw_metrics.items():
        if prom_name in METRIC_MAP:
            normalized[METRIC_MAP[prom_name]] = value

    return normalized

def stream_metrics():
    """
    Generator that yields (timestamp, normalized_metrics)
    """
    while True:
        try:
            response = requests.get(METRICS_URL, timeout=3)
            response.raise_for_status()

            raw = parse_prometheus_text(response.text)
            normalized = normalize_metrics(raw)

            yield time.time(), normalized

        except Exception as e:
            print(f"[WARN] Metrics fetch failed: {e}")

        time.sleep(POLL_INTERVAL)
