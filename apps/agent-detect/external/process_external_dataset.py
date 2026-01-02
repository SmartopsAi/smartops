import sys
import os
import csv
from datetime import datetime

# ---------------------------------------------------
# Fix Python path
# ---------------------------------------------------
BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, BASE_DIR)

from features.windowing import SlidingWindow
from features.feature_engineering import build_feature_vector

# ---------------------------------------------------
# CONFIG
# ---------------------------------------------------
INPUT_DIR = "external_datasets/realAWSCloudwatch"
OUTPUT_CSV = "data/datasets/aws_external_features.csv"

FEATURE_METRICS = ["value"]
WINDOW_SIZE_SECONDS = 60

# Explicit feature schema (research-stable)
FEATURE_KEYS = [
    "value_mean",
    "value_std",
    "value_min",
    "value_max",
    "value_slope",
    "value_spike"
]

# ---------------------------------------------------
# Timestamp normalization
# ---------------------------------------------------
def parse_timestamp(ts):
    try:
        return float(ts)
    except ValueError:
        return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp()

# ---------------------------------------------------
def process_file(filepath, source_name, writer):
    window = SlidingWindow(WINDOW_SIZE_SECONDS)

    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = parse_timestamp(row["timestamp"])
            value = float(row["value"])
            label = int(row.get("label", row.get("anomaly", 0)))

            window.add(ts, {"value": value})

            if window.is_ready():
                feats = build_feature_vector(
                    window.values(), FEATURE_METRICS
                )

                if feats:
                    record = {k: feats[k] for k in FEATURE_KEYS}
                    record["label"] = label
                    record["source"] = source_name
                    writer.writerow(record)

# ---------------------------------------------------
def main():
    os.makedirs("data/datasets", exist_ok=True)

    files = [
        f for f in os.listdir(INPUT_DIR)
        if f.endswith(".csv")
    ]

    if not files:
        print("[ERROR] No CSV files found")
        return

    fieldnames = FEATURE_KEYS + ["label", "source"]

    with open(OUTPUT_CSV, "w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()

        for filename in files:
            filepath = os.path.join(INPUT_DIR, filename)
            source_name = filename.replace(".csv", "")
            print(f"[PROCESSING] {filename}")
            process_file(filepath, source_name, writer)

    print(f"[OK] AWS external features saved to {OUTPUT_CSV}")

# ---------------------------------------------------
if __name__ == "__main__":
    main()
