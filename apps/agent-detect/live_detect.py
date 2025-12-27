from models.stats_baseline import StatisticalBaseline
from models.isolation_forest import IsolationForestModel
import csv

DATASET_FILE = "data/datasets/features.csv"

def load_training_features():
    X = []
    with open(DATASET_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            row.pop("timestamp")
            row.pop("label")
            X.append({k: float(v) for k, v in row.items()})
    return X

class LiveAnomalyDetector:
    def __init__(self):
        X = load_training_features()

        # Train models
        self.stats = StatisticalBaseline()
        self.stats.fit(X)

        self.iso = IsolationForestModel()
        self.iso.fit([list(x.values()) for x in X])

        self.feature_keys = list(X[0].keys())

    def detect(self, feature_vector):
        x = [feature_vector[k] for k in self.feature_keys]

        stats_anomaly = self.stats.predict(feature_vector)
        iso_anomaly = self.iso.predict(x)

        return {
            "statistical": stats_anomaly,
            "isolation_forest": iso_anomaly,
            "final": stats_anomaly or iso_anomaly
        }
