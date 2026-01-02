from pathlib import Path
import json

BASE_DIR = Path(".")
RUNTIME_DIR = BASE_DIR / "data/runtime"

def _load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None

def load_runtime_signals():
    detection = _load_json(RUNTIME_DIR / "latest_detection.json") or {}
    rca = _load_json(RUNTIME_DIR / "latest_rca.json") or {}
    features = _load_json(RUNTIME_DIR / "latest_features.json") or {}

    anomaly_flag = bool(detection.get("anomaly", False))

    # anomaly.type is best taken from RCA when available
    detected_anomaly = rca.get("detected_anomaly")
    anomaly_type = detected_anomaly if detected_anomaly else ("unknown" if anomaly_flag else "none")

    confidence = float(rca.get("confidence", 0.0)) if anomaly_flag else 0.0

    root = rca.get("root_cause") or {}
    # naive "cause" mapping (can improve later)
    signal = (root.get("signal") or "").lower()
    rca_type = (root.get("type") or "").lower()

    if "cpu" in signal or "cpu" in rca_type:
        rca_cause = "cpu_saturation"
    elif "memory" in signal or "leak" in rca_type:
        rca_cause = "memory_leak"
    elif "timeout" in rca_type or "latency" in signal:
        rca_cause = "latency_jitter"
    else:
        rca_cause = "unknown"

    dsl_signal = {
        "anomaly.type": anomaly_type,
        "anomaly.score": 1.0 if anomaly_flag else 0.0,
        "rca.cause": rca_cause,
        "rca.probability": confidence,
        "raw": {
            "detection": detection,
            "rca": rca,
            "features": features
        }
    }
    return dsl_signal
