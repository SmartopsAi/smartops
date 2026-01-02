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

def main():
    X, y = load_dataset()

    # Train baseline
    stats = StatisticalBaseline()
    stats.fit(X)

    # Train Isolation Forest
    iso = IsolationForestModel()
    iso.fit([list(x.values()) for x in X])

    print("[OK] Models trained successfully")

if __name__ == "__main__":
    main()
