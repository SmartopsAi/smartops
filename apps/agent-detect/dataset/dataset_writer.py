import csv
import os
from datetime import datetime

DATASET_DIR = "data/datasets"
DATASET_FILE = os.path.join(DATASET_DIR, "features.csv")

class DatasetWriter:
    def __init__(self):
        os.makedirs(DATASET_DIR, exist_ok=True)
        self.file_exists = os.path.exists(DATASET_FILE)

    def write(self, timestamp, features, label):
        row = {
            "timestamp": datetime.fromtimestamp(timestamp).isoformat(),
            **features,
            "label": label
        }

        with open(DATASET_FILE, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())

            if not self.file_exists:
                writer.writeheader()
                self.file_exists = True

            writer.writerow(row)
