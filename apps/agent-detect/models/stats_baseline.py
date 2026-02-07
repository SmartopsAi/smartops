import numpy as np


class StatisticalBaseline:
    """
    Robust statistical baseline using z-score.

    Design goals:
    - Tolerate missing features (schema evolution safe)
    - Never crash live detection
    - Simulator-only (ERP uses Isolation Forest)
    """

    def __init__(self, z_threshold=3.0):
        self.z_threshold = z_threshold
        self.mean = {}
        self.std = {}

    def fit(self, X):
        """
        X: list of feature dicts
        """
        if not X:
            return

        keys = X[0].keys()

        for k in keys:
            values = [row[k] for row in X if k in row]
            if not values:
                continue
            self.mean[k] = np.mean(values)
            self.std[k] = np.std(values) + 1e-6

    def score(self, x):
        """
        Returns anomaly score (max z-score).
        Missing features are ignored safely.
        """
        scores = []

        for k, v in x.items():
            if k not in self.mean or k not in self.std:
                continue
            z = abs(v - self.mean[k]) / self.std[k]
            scores.append(z)

        # If no comparable features, assume normal
        return max(scores) if scores else 0.0

    def predict(self, x):
        return self.score(x) > self.z_threshold
