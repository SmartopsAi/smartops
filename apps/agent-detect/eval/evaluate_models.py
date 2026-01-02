import sys
import os

# Add agent-detect root to Python path
BASE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
sys.path.insert(0, BASE_DIR)

import csv
from models.stats_baseline import StatisticalBaseline
from models.isolation_forest import IsolationForestModel


DATASET_FILE = "data/datasets/features.csv"

def load_dataset():
    X, y = [], []

    with open(DATASET_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = int(row.pop("label"))
            row.pop("timestamp")
            X.append({k: float(v) for k, v in row.items()})
            y.append(label)

    return X, y

def confusion_matrix(y_true, y_pred):
    tp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 1)
    fp = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 1)
    fn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 1 and yp == 0)
    tn = sum(1 for yt, yp in zip(y_true, y_pred) if yt == 0 and yp == 0)
    return tp, fp, fn, tn

def precision(tp, fp):
    return tp / (tp + fp) if (tp + fp) else 0.0

def recall(tp, fn):
    return tp / (tp + fn) if (tp + fn) else 0.0

def evaluate():
    X, y = load_dataset()

    # Train models
    stats = StatisticalBaseline()
    stats.fit(X)

    iso = IsolationForestModel()
    iso.fit([list(x.values()) for x in X])

    # Predictions
    y_pred_stats = [int(stats.predict(x)) for x in X]
    y_pred_iso = [int(iso.predict(list(x.values()))) for x in X]

    # Metrics
    for name, preds in [
        ("Statistical Baseline", y_pred_stats),
        ("Isolation Forest", y_pred_iso)
    ]:
        tp, fp, fn, tn = confusion_matrix(y, preds)
        p = precision(tp, fp)
        r = recall(tp, fn)

        print(f"\n=== {name} ===")
        print(f"TP: {tp}, FP: {fp}, FN: {fn}, TN: {tn}")
        print(f"Precision: {p:.3f}")
        print(f"Recall:    {r:.3f}")

if __name__ == "__main__":
    evaluate()
