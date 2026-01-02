from sklearn.ensemble import IsolationForest

class IsolationForestModel:
    def __init__(self):
        self.model = IsolationForest(
            n_estimators=100,
            contamination=0.05,
            random_state=42
        )

    def fit(self, X):
        self.model.fit(X)

    def score(self, x):
        return -self.model.score_samples([x])[0]

    def predict(self, x):
        return self.model.predict([x])[0] == -1
