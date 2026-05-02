from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

UNMATCHED_STORE_ENV = "UNMATCHED_ANOMALY_STORE_PATH"
DEFAULT_UNMATCHED_STORE_PATH = "/policy_engine/store/unmatched_anomalies.jsonl"
ALLOWED_STATUSES = {"new", "drafted", "ignored", "resolved"}


def get_unmatched_store_path() -> Path:
    return Path(os.getenv(UNMATCHED_STORE_ENV, DEFAULT_UNMATCHED_STORE_PATH))


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _get_nested(data: dict[str, Any], path: str, default=None):
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur.get(part)
    return cur


def _field(signal: dict[str, Any], nested_path: str, flat_key: str | None = None, default=None):
    value = _get_nested(signal, nested_path, None)
    if value is not None:
        return value
    if flat_key and flat_key in signal:
        return signal.get(flat_key)
    return default


def _signal_fingerprint_parts(signal: dict[str, Any]) -> dict[str, Any]:
    metadata = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
    raw = signal.get("raw") if isinstance(signal.get("raw"), dict) else {}
    incoming = raw.get("incoming") if isinstance(raw.get("incoming"), dict) else {}

    service = signal.get("service") or incoming.get("service") or "unknown"
    anomaly_type = _field(signal, "anomaly.type", "anomaly.type", "unknown")
    risk = metadata.get("risk") or _field(signal, "risk", "risk", None) or "unknown"
    rca_cause = _field(signal, "rca.cause", "rca.cause", None) or "unknown"

    return {
        "service": str(service),
        "anomaly_type": str(anomaly_type),
        "rca_cause": str(rca_cause),
        "risk": str(risk),
    }


def compute_signal_hash(signal: dict[str, Any]) -> str:
    parts = _signal_fingerprint_parts(signal)
    raw = "|".join(
        [
            parts["service"],
            parts["anomaly_type"],
            parts["rca_cause"],
            parts["risk"],
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _read_records() -> list[dict[str, Any]]:
    path = get_unmatched_store_path()
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return []

    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except Exception:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _write_records_atomic(records: list[dict[str, Any]]) -> None:
    path = get_unmatched_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")

    with tmp_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

    os.replace(tmp_path, path)


def _to_float(value: Any):
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return value


def record_unmatched_anomaly(signal: dict[str, Any], reason: str = "no policy matched") -> dict[str, Any] | None:
    try:
        records = _read_records()
        signal_hash = compute_signal_hash(signal)
        now = _utc_now()

        for record in records:
            if record.get("signal_hash") == signal_hash:
                record["last_seen"] = now
                record["count"] = int(record.get("count") or 0) + 1
                record["source_decision"] = reason
                _write_records_atomic(records)
                return record

        parts = _signal_fingerprint_parts(signal)
        metadata = signal.get("metadata") if isinstance(signal.get("metadata"), dict) else {}
        raw = signal.get("raw") if isinstance(signal.get("raw"), dict) else {}
        incoming = raw.get("incoming") if isinstance(raw.get("incoming"), dict) else {}

        record = {
            "id": f"ua-{signal_hash}",
            "window_id": signal.get("windowId") or signal.get("window_id") or incoming.get("windowId"),
            "service": parts["service"],
            "anomaly_type": parts["anomaly_type"],
            "score": _to_float(_field(signal, "anomaly.score", "anomaly.score", None)),
            "risk": parts["risk"],
            "rca_cause": parts["rca_cause"],
            "rca_probability": _to_float(_field(signal, "rca.probability", "rca.probability", None)),
            "signal_hash": signal_hash,
            "first_seen": now,
            "last_seen": now,
            "count": 1,
            "status": "new",
            "draft_policy_id": None,
            "resolved_by": None,
            "source_decision": reason,
        }

        records.append(record)
        _write_records_atomic(records)
        return record
    except Exception:
        return None


def list_unmatched_anomalies(limit: int = 50, status: str | None = None) -> dict[str, Any]:
    records = _read_records()
    if status:
        records = [record for record in records if record.get("status") == status]

    records.sort(key=lambda item: str(item.get("last_seen") or ""), reverse=True)
    limited = records[: max(1, limit)]

    return {
        "status": "ok",
        "source": "unmatched-anomaly-store",
        "store_path": str(get_unmatched_store_path()),
        "count": len(limited),
        "items": limited,
    }


def update_unmatched_status(
    unmatched_id: str,
    status: str,
    updated_by: str,
    reason: str | None = None,
    draft_policy_id: str | None = None,
) -> dict[str, Any] | None:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Unsupported unmatched anomaly status: {status}")

    records = _read_records()
    now = _utc_now()
    for record in records:
        if record.get("id") != unmatched_id:
            continue

        record["status"] = status
        record["updated_at"] = now
        record["updated_by"] = updated_by
        record["status_reason"] = reason
        if draft_policy_id is not None:
            record["draft_policy_id"] = draft_policy_id
        if status == "resolved":
            record["resolved_by"] = updated_by

        _write_records_atomic(records)
        return record

    return None
