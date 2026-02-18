import os
import csv
from pathlib import Path

from models.stats_baseline import StatisticalBaseline
from models.isolation_forest import IsolationForestModel

PROFILE = os.getenv("PROFILE", "simulator")

BASE_DIR = Path(__file__).resolve().parent
DATASET_FILE = BASE_DIR / "data" / "datasets" / "features.csv"


def load_training_features():
    """
    Load simulator training features from CSV.
    Used ONLY in simulator mode.
    If dataset does not exist, return None safely.
    """
    if not DATASET_FILE.exists():
        print(f"[LiveDetect] WARNING: Training dataset not found at {DATASET_FILE}. Running without static training.")
        return None

    X = []
    with open(DATASET_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            row.pop("timestamp", None)
            row.pop("label", None)
            X.append({k: float(v) for k, v in row.items()})

    if not X:
        print("[LiveDetect] WARNING: Training dataset empty. Running without static training.")
        return None

    return X


class LiveAnomalyDetector:
    def __init__(self):
        self.profile = PROFILE

        # -------------------------------
        # SIMULATOR MODE (legacy, stable)
        # -------------------------------
        if self.profile == "simulator":
            X = load_training_features()

            # If dataset missing → fallback to dynamic mode
            if X is None:
                self.stats = None
                self.iso = IsolationForestModel()
                self.feature_keys = None
                print("[LiveDetect] Simulator fallback mode enabled (no training dataset).")

            else:
                self.stats = StatisticalBaseline()
                self.stats.fit(X)

                self.iso = IsolationForestModel()
                self.iso.fit([list(x.values()) for x in X])

                self.feature_keys = list(X[0].keys())

        # -------------------------------
        # ERP / ODOO MODE (production)
        # -------------------------------
        else:
            self.stats = None
            self.iso = IsolationForestModel()
            self.feature_keys = None

    def detect(self, feature_vector):
        """
        Perform anomaly detection.
        Returns consistent schema across profiles.
        """

        # -------------------------------
        # SIMULATOR TRAINED PATH
        # -------------------------------
        if self.profile == "simulator" and self.feature_keys is not None:
            x = [feature_vector[k] for k in self.feature_keys]

            stats_anomaly = self.stats.predict(feature_vector)
            iso_anomaly = self.iso.predict(x)

            return {
                "statistical": stats_anomaly,
                "isolation_forest": iso_anomaly,
                "final": stats_anomaly or iso_anomaly,
            }

        # -------------------------------
        # FALLBACK / ERP PATH
        # -------------------------------
        # Works without training dataset
        values = list(feature_vector.values())

        iso_anomaly = self.iso.predict(values)

        return {
            "statistical": False,
            "isolation_forest": iso_anomaly,
            "final": iso_anomaly,
        }
