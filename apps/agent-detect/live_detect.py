import os
import csv
from pathlib import Path

from models.stats_baseline import StatisticalBaseline
from models.isolation_forest import IsolationForestModel

PROFILE = os.getenv("PROFILE", "simulator")
ISO_ENABLED = os.getenv("ISO_ENABLED", "1") == "1"

BASE_DIR = Path(__file__).resolve().parent
DATASET_FILE = BASE_DIR / "data" / "datasets" / "features.csv"


def load_training_features():
    """
    Load simulator training features from CSV.
    Used ONLY in simulator mode.
    If dataset does not exist, return None safely.
    """
    if not DATASET_FILE.exists():
        print(
            f"[LiveDetect] WARNING: Training dataset not found at {DATASET_FILE}. Running without static training."
        )
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
        self.iso_enabled = ISO_ENABLED

        # -------------------------------
        # SIMULATOR MODE (legacy, stable)
        # -------------------------------
        if self.profile == "simulator":
            X = load_training_features()

            # If dataset missing → fallback to dynamic mode
            if X is None:
                self.stats = None
                self.iso = IsolationForestModel() if self.iso_enabled else None
                self.feature_keys = None
                print("[LiveDetect] Simulator fallback mode enabled (no training dataset).")
                print(f"[LiveDetect] ISO_ENABLED={'1' if self.iso_enabled else '0'}")

            else:
                self.stats = StatisticalBaseline()
                self.stats.fit(X)

                # Keep feature order stable
                self.feature_keys = list(X[0].keys())

                if self.iso_enabled:
                    self.iso = IsolationForestModel()
                    self.iso.fit([[x[k] for k in self.feature_keys] for x in X])
                else:
                    self.iso = None

                print(f"[LiveDetect] ISO_ENABLED={'1' if self.iso_enabled else '0'}")

        # -------------------------------
        # ERP / ODOO MODE (production)
        # -------------------------------
        else:
            self.stats = None
            self.iso = IsolationForestModel() if self.iso_enabled else None
            self.feature_keys = None
            print(f"[LiveDetect] ISO_ENABLED={'1' if self.iso_enabled else '0'}")

    def detect(self, feature_vector):
        """
        Perform anomaly detection.
        Returns consistent schema across profiles.
        """

        # -------------------------------
        # SIMULATOR TRAINED PATH
        # -------------------------------
        if self.profile == "simulator" and self.feature_keys is not None:
            x = [feature_vector.get(k, 0.0) for k in self.feature_keys]

            stats_anomaly = bool(self.stats.predict(feature_vector)) if self.stats else False

            iso_anomaly = False
            if self.iso is not None:
                try:
                    iso_anomaly = bool(self.iso.predict(x))
                except Exception as e:
                    print(f"[LiveDetect] ISO error (disabled for this window): {e}")
                    iso_anomaly = False

            return {
                "statistical": stats_anomaly,
                "isolation_forest": iso_anomaly,
                "final": stats_anomaly or iso_anomaly,
            }

        # -------------------------------
        # FALLBACK / ERP PATH (no dataset)
        # -------------------------------
        # Use stable ordering to avoid feature-count mismatch and inhomogeneous shapes
        keys = sorted(feature_vector.keys())
        values = [feature_vector.get(k, 0.0) for k in keys]

        iso_anomaly = False
        if self.iso is not None:
            try:
                iso_anomaly = bool(self.iso.predict(values))
            except Exception as e:
                print(f"[LiveDetect] ISO error (disabled for this window): {e}")
                iso_anomaly = False

        return {
            "statistical": False,
            "isolation_forest": iso_anomaly,
            "final": iso_anomaly,
        }