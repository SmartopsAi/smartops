import numpy as np

class StatisticalBaseline:
    def __init__(self, z_threshold=3.0):
        self.z_threshold = z_threshold
        self.mean = {}
        self.std = {}

    def fit(self, X):
        """
        X: list of feature dicts
        """
        keys = X[0].keys()

        for k in keys:
            values = [row[k] for row in X]
            self.mean[k] = np.mean(values)
            self.std[k] = np.std(values) + 1e-6

    def score(self, x):
        """
        Returns anomaly score
        """
        scores = []

        for k, v in x.items():
            z = abs(v - self.mean[k]) / self.std[k]
            scores.append(z)

        return max(scores)

    def predict(self, x):
        return self.score(x) > self.z_threshold
