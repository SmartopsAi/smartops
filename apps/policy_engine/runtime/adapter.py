from pathlib import Path
import json

# Policy Engine reads runtime outputs produced by Agent Detect
BASE_DIR = Path(__file__).resolve().parents[3]
RUNTIME_DIR = BASE_DIR / "apps/agent-detect/data/runtime"


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

    # -------------------------------
    # Derive anomaly.type
    # -------------------------------
    detected_anomaly = rca.get("detected_anomaly")
    if detected_anomaly:
        anomaly_type = detected_anomaly
    else:
        anomaly_type = "unknown" if anomaly_flag else "none"

    anomaly_score = 1.0 if anomaly_flag else 0.0

    # -------------------------------
    # Derive RCA cause
    # -------------------------------
    confidence = float(rca.get("confidence", 0.0)) if anomaly_flag else 0.0

    root = rca.get("root_cause") or {}
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

    # -------------------------------
    # IMPORTANT: Nested structure
    # -------------------------------
    dsl_signal = {
        "anomaly": {
            "type": anomaly_type,
            "score": anomaly_score,
        },
        "rca": {
            "cause": rca_cause,
            "probability": confidence,
        },
        "service": rca.get("service", "erp-simulator"),
        "raw": {
            "detection": detection,
            "rca": rca,
            "features": features,
        },
    }

    return dsl_signal
