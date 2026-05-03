import json
import os
import logging
from typing import List, Optional
from datetime import datetime, timezone
from pathlib import Path

from services.dto import (
    AnomalyEvent,
    RcaReport,
    PolicyDecision,
    FeatureSnapshot
)

logger = logging.getLogger("dashboard.reader")


def _iso_to_epoch(ts_raw: Optional[str]) -> float:
    """
    Convert ISO-8601 timestamp (e.g., 2026-02-25T12:00:00Z) to epoch seconds.
    Returns 0.0 on failure/None.
    """
    if not ts_raw:
        return 0.0
    try:
        # Support trailing 'Z'
        ts = ts_raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


class ArtifactReader:
    """
    Reads runtime artifacts for the SmartOps dashboard.

    Priority:
    1) ARTIFACT_DIR env var (if set)
    2) In-cluster mounted path: /data/runtime
    3) Repo-root fallback: <project_root>/data/runtime
    """

    def __init__(self):
        # Resolve "project_root" (repo root) for local fallback only
        current_file = Path(__file__).resolve()
        services_dir = current_file.parent
        dashboard_dir = services_dir.parent
        apps_dir = dashboard_dir.parent
        project_root = apps_dir.parent  # <repo_root> when running locally
        self.project_root = str(project_root)

        # Decide runtime directory
        in_cluster = bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
        env_artifact_dir = os.getenv("ARTIFACT_DIR")

        if env_artifact_dir:
            runtime_dir = Path(env_artifact_dir).expanduser()
        elif in_cluster:
            runtime_dir = Path("/data/runtime")
        else:
            runtime_dir = project_root / "data" / "runtime"

        self.runtime_dir = runtime_dir

        dashboard_evidence_dir = os.getenv("DASHBOARD_EVIDENCE_DIR")
        if dashboard_evidence_dir:
            dashboard_evidence_dir_path = Path(dashboard_evidence_dir).expanduser()
        else:
            dashboard_evidence_dir_path = runtime_dir

        latest_evidence_path = Path(
            os.getenv(
                "DASHBOARD_LATEST_EVIDENCE_PATH",
                str(dashboard_evidence_dir_path / "latest_anomaly_evidence.json"),
            )
        ).expanduser()
        anomaly_history_path = Path(
            os.getenv(
                "DASHBOARD_ANOMALY_HISTORY_PATH",
                str(dashboard_evidence_dir_path / "anomaly_history.jsonl"),
            )
        ).expanduser()

        # Policy audit log path (optional file-based)
        # In your current deployment you rely on Policy Engine API more than file, so this can stay optional.
        audit_log_env = os.getenv("AUDIT_LOG_PATH")
        if audit_log_env:
            audit_log_path = Path(audit_log_env).expanduser()
        else:
            audit_log_path = project_root / "policy_engine" / "audit" / "policy_decisions.jsonl"

        self.paths = {
            "detection": runtime_dir / "latest_detection.json",
            "features": runtime_dir / "latest_features.json",
            "rca": runtime_dir / "latest_rca.json",
            "audit_log": audit_log_path,
            "latest_anomaly_evidence": latest_evidence_path,
            "anomaly_history": anomaly_history_path,
        }

        print("--- ARTIFACT READER DEBUG ---")
        for k, v in self.paths.items():
            try:
                p = Path(v)
                print(f"{k}: {str(p)} (exists={p.exists()})")
            except Exception as e:
                print(f"{k}: {v} (exists=ERROR: {e})")
        print("-----------------------------")

    # ----------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------

    def _read_json(self, path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to read %s: %s", str(path), e)
            return None

    # ----------------------------------------------------
    # Persistent anomaly evidence
    # ----------------------------------------------------

    def get_latest_anomaly_evidence(self) -> Optional[dict]:
        return self._read_json(Path(self.paths["latest_anomaly_evidence"]))

    def get_anomaly_history(self, limit: int = 10) -> list[dict]:
        path = Path(self.paths["anomaly_history"])
        if not path.exists():
            return []

        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception as e:
            logger.debug("Failed reading anomaly history %s: %s", str(path), e)
            return []

        events = []
        for line in lines[-limit:]:
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                continue

        return list(reversed(events))

    # ----------------------------------------------------
    # Detection / Anomaly
    # ----------------------------------------------------

    def get_latest_anomaly(self) -> Optional[AnomalyEvent]:
        data = self._read_json(Path(self.paths["detection"]))
        if not data:
            return None

        is_anomaly = bool(data.get("anomaly", False))
        score = 1.0 if is_anomaly else 0.0

        # Accept multiple field names (your generated sample uses "ts")
        ts = data.get("timestamp", None)
        if ts is None:
            ts = _iso_to_epoch(data.get("ts"))
        if ts is None:
            ts = 0.0

        return AnomalyEvent(
            ts=float(ts),
            service=str(data.get("service", "erp-simulator")),
            score=score,
            anomaly_type=(
                "statistical"
                if data.get("statistical")
                else "isolation_forest"
                if data.get("isolation_forest")
                else "normal"
            ),
            model="ensemble",
            features_ref=None,
        )

    # ----------------------------------------------------
    # Feature snapshot
    # ----------------------------------------------------

    def get_latest_features(self) -> Optional[FeatureSnapshot]:
        data = self._read_json(Path(self.paths["features"]))
        if not data:
            return None

        ts = data.get("timestamp", None)
        if ts is None:
            ts = _iso_to_epoch(data.get("ts"))
        if ts is None:
            ts = 0.0

        # Support both "window_id" and "windowId"
        window_id = data.get("window_id") or data.get("windowId") or "unknown"

        # Support both list and dict schema
        feats = data.get("features", [])
        if isinstance(feats, dict):
            feats = [{"name": k, "value": v} for k, v in feats.items()]

        return FeatureSnapshot(
            ts=float(ts),
            window_id=str(window_id),
            top_features=feats,
        )

    # ----------------------------------------------------
    # RCA
    # ----------------------------------------------------

    def get_latest_rca(self) -> Optional[RcaReport]:
        data = self._read_json(Path(self.paths["rca"]))
        if not data:
            return None

        ts = data.get("timestamp", None)
        if ts is None:
            ts = _iso_to_epoch(data.get("ts"))
        if ts is None:
            ts = 0.0

        evidence = data.get("evidence", {})
        if isinstance(evidence, list):
            evidence = {"trace_ids": [], "logs": []}

        root_cause = data.get("root_cause") or data.get("rootCause")
        ranked_causes = [root_cause] if root_cause else []

        incident_id = data.get("anomaly_id") or data.get("incident_id") or data.get("windowId") or "unknown"

        return RcaReport(
            ts=float(ts),
            incident_id=str(incident_id),
            ranked_causes=ranked_causes,
            evidence=evidence,
        )

    # ----------------------------------------------------
    # Policy decisions (file-based optional)
    # ----------------------------------------------------

    def get_recent_decisions(self, limit: int = 50) -> List[PolicyDecision]:
        path = Path(self.paths["audit_log"])
        if not path.exists():
            return []

        decisions: List[PolicyDecision] = []

        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        except Exception as e:
            logger.debug("Failed reading audit log %s: %s", str(path), e)
            return []

        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)

                ts = _iso_to_epoch(entry.get("ts_utc")) or float(entry.get("ts", 0.0))

                decision_raw = entry.get("decision", "no_action")
                guardrail_reason = entry.get("guardrail_reason") or entry.get("guardrailReason")

                if decision_raw == "action":
                    decision = "allow"
                elif decision_raw == "blocked" or guardrail_reason == "blocked":
                    decision = "block"
                else:
                    decision = "no_action"

                guardrails = []
                if guardrail_reason:
                    guardrails.append({
                        "name": entry.get("policy", "unknown"),
                        "triggered": (decision == "block"),
                    })

                recommended_actions = []
                action_plan = entry.get("action_plan") or entry.get("actionPlan")
                if isinstance(action_plan, dict) and action_plan.get("type"):
                    recommended_actions.append(action_plan.get("type"))

                decisions.append(
                    PolicyDecision(
                        ts=float(ts),
                        policy_id=entry.get("policy", "n/a"),
                        decision=decision,
                        reason=entry.get("reason", guardrail_reason or ""),
                        guardrails=guardrails,
                        recommended_actions=recommended_actions,
                    )
                )
            except Exception as e:
                logger.debug("Skipping audit entry: %s", e)
                continue

        return sorted(decisions, key=lambda d: d.ts, reverse=True)
