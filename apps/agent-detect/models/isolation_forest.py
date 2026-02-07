from sklearn.ensemble import IsolationForest


class IsolationForestModel:
    """
    Isolation Forest with lazy / online fitting support.

    - Simulator mode: fit() is called explicitly with offline data
    - ERP mode: model auto-fits after warm-up window
    """

    def __init__(self, warmup_samples: int = 20):
        self.model = IsolationForest(
            n_estimators=100,
            contamination=0.05,
            random_state=42
        )

        self.warmup_samples = warmup_samples
        self._buffer = []
        self._fitted = False

    # -------------------------------
    # Explicit training (simulator)
    # -------------------------------
    def fit(self, X):
        if not X:
            return
        self.model.fit(X)
        self._fitted = True

    # -------------------------------
    # Prediction with auto-fit (ERP)
    # -------------------------------
    def predict(self, x):
        """
        Returns True if anomaly, False otherwise.
        """

        # If not fitted yet, collect warm-up samples
        if not self._fitted:
            self._buffer.append(x)

            # Still warming up → assume normal
            if len(self._buffer) < self.warmup_samples:
                return False

            # Warm-up complete → fit once
            self.model.fit(self._buffer)
            self._fitted = True
            self._buffer.clear()

            # First fitted prediction treated as normal
            return False

        # Normal prediction path
        return self.model.predict([x])[0] == -1

    # -------------------------------
    # Optional scoring (future use)
    # -------------------------------
    def score(self, x):
        if not self._fitted:
            return 0.0
        return -self.model.score_samples([x])[0]
