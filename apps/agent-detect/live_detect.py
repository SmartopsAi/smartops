import os
import csv
from pathlib import Path

from models.stats_baseline import StatisticalBaseline
from models.isolation_forest import IsolationForestModel

PROFILE = os.getenv("PROFILE", "simulator")

BASE_DIR = Path(__file__).resolve().parents[2]  # smartops/
DATASET_FILE = BASE_DIR / "data" / "datasets" / "features.csv"


def load_training_features():
    """
    Load simulator training features from CSV.
    Used ONLY in simulator mode.
    """
    X = []
    with open(DATASET_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            row.pop("timestamp", None)
            row.pop("label", None)
            X.append({k: float(v) for k, v in row.items()})
    return X


class LiveAnomalyDetector:
    def __init__(self):
        self.profile = PROFILE

        # -------------------------------
        # SIMULATOR MODE (legacy, stable)
        # -------------------------------
        if self.profile == "simulator":
            X = load_training_features()

            self.stats = StatisticalBaseline()
            self.stats.fit(X)

            self.iso = IsolationForestModel()
            self.iso.fit([list(x.values()) for x in X])

            self.feature_keys = list(X[0].keys())

        # -------------------------------
        # ERP / ODOO MODE (production)
        # -------------------------------
        else:
            # No static training data
            # Isolation Forest works on live feature vectors
            self.stats = None
            self.iso = IsolationForestModel()
            self.feature_keys = None

    def detect(self, feature_vector):
        """
        Perform anomaly detection.
        Returns consistent schema across profiles.
        """

        # -------------------------------
        # SIMULATOR PATH
        # -------------------------------
        if self.profile == "simulator":
            x = [feature_vector[k] for k in self.feature_keys]

            stats_anomaly = self.stats.predict(feature_vector)
            iso_anomaly = self.iso.predict(x)

            return {
                "statistical": stats_anomaly,
                "isolation_forest": iso_anomaly,
                "final": stats_anomaly or iso_anomaly,
            }

        # -------------------------------
        # ERP / ODOO PATH
        # -------------------------------
        # Use only Isolation Forest on live features
        values = list(feature_vector.values())

        iso_anomaly = self.iso.predict(values)

        return {
            "statistical": False,
            "isolation_forest": iso_anomaly,
            "final": iso_anomaly,
        }
