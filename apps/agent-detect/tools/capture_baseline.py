import requests
import time
import json
import os

METRICS_URL = "http://localhost:9000/metrics"
OUTPUT_FILE = "data/baseline/normal_run.json"
INTERVAL = 5          # seconds
SAMPLES = 60          # 60 samples ≈ 5 minutes (increase later)

# Ensure directory exists
os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

print("[INFO] Starting baseline capture...")
print(f"[INFO] Saving to {OUTPUT_FILE}")

data = []

for i in range(SAMPLES):
    try:
        resp = requests.get(METRICS_URL, timeout=3)
        resp.raise_for_status()

        data.append({
            "timestamp": time.time(),
            "metrics": resp.text
        })

        print(f"[OK] Collected sample {i+1}/{SAMPLES}")
    except Exception as e:
        print(f"[ERROR] Failed to collect metrics: {e}")

    time.sleep(INTERVAL)

with open(OUTPUT_FILE, "w") as f:
    json.dump(data, f, indent=2)

print("[DONE] Baseline capture completed.")
print(f"[DONE] Total samples collected: {len(data)}")
