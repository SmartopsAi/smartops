from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path
import json
import csv

app = FastAPI()

BASE_DIR = Path(".")
RUNTIME_DIR = BASE_DIR / "data/runtime"
DATASET_FILE = BASE_DIR / "data/datasets/features.csv"

# -----------------------------------
# Helpers
# -----------------------------------
def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None

# -----------------------------------
# Routes
# -----------------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    with open("apps/dashboard/templates/index.html", encoding="utf-8") as f:
        return f.read()

@app.get("/api/rca/latest")
def latest_rca():
    data = load_json(RUNTIME_DIR / "latest_rca.json")
    return data if data else {"status": "no_rca"}


@app.get("/api/detection/status")
def detection_status():
    data = load_json(RUNTIME_DIR / "latest_detection.json")
    return data if data else {"status": "no_data"}

@app.get("/api/prediction/risk")
def prediction_risk():
    data = load_json(RUNTIME_DIR / "latest_risk.json")
    return data if data else {"risk": "UNKNOWN"}

@app.get("/api/dataset/stats")
def dataset_stats():
    if not DATASET_FILE.exists():
        return {"windows": 0, "labels": {}}

    normal = 0
    anomaly = 0
    total = 0

    with open(DATASET_FILE, newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            total += 1
            if row[-1] == "1":
                anomaly += 1
            else:
                normal += 1

    return {
        "windows": total,
        "labels": {
            "normal": normal,
            "anomaly": anomaly
        }
    }
