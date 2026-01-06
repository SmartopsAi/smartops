import json
import os
import logging
from typing import List, Optional
from datetime import datetime

from services.dto import (
    AnomalyEvent,
    RcaReport,
    PolicyDecision,
    FeatureSnapshot
)

logger = logging.getLogger("dashboard.reader")


class ArtifactReader:
    def __init__(self):
        # Resolve project root safely
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        dashboard_dir = os.path.dirname(services_dir)
        apps_dir = os.path.dirname(dashboard_dir)
        self.project_root = os.path.dirname(apps_dir)

        self.paths = {
            "detection": os.path.join(self.project_root, "data", "runtime", "latest_detection.json"),
            "features": os.path.join(self.project_root, "data", "runtime", "latest_features.json"),
            "rca": os.path.join(self.project_root, "data", "runtime", "latest_rca.json"),
            "audit_log": os.path.join(
                self.project_root,
                "policy_engine",
                "audit",
                "policy_decisions.jsonl"
            ),
        }

        print("--- ARTIFACT READER DEBUG ---")
        for k, v in self.paths.items():
            print(f"{k}: {v} (exists={os.path.exists(v)})")
        print("-----------------------------")

    # ----------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------

    def _read_json(self, path: str) -> Optional[dict]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read {path}: {e}")
            return None

    # ----------------------------------------------------
    # Detection / Anomaly
    # ----------------------------------------------------

    def get_latest_anomaly(self) -> Optional[AnomalyEvent]:
        data = self._read_json(self.paths["detection"])
        if not data:
            return None

        is_anomaly = bool(data.get("anomaly", False))
        score = 1.0 if is_anomaly else 0.0

        return AnomalyEvent(
            ts=data.get("timestamp", 0.0),
            service="erp-simulator",
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
        data = self._read_json(self.paths["features"])
        if not data:
            return None

        return FeatureSnapshot(
            ts=data.get("timestamp", 0.0),
            window_id=data.get("window_id", "unknown"),
            top_features=data.get("features", []),
        )

    # ----------------------------------------------------
    # RCA
    # ----------------------------------------------------

    def get_latest_rca(self) -> Optional[RcaReport]:
        data = self._read_json(self.paths["rca"])
        if not data:
            return None

        evidence = data.get("evidence", {})
        if isinstance(evidence, list):
            evidence = {"trace_ids": [], "logs": []}

        root_cause = data.get("root_cause")
        ranked_causes = [root_cause] if root_cause else []

        return RcaReport(
            ts=data.get("timestamp", 0.0),
            incident_id=data.get("anomaly_id", "unknown"),
            ranked_causes=ranked_causes,
            evidence=evidence,
        )

    # ----------------------------------------------------
    # Policy decisions (REAL policy engine parsing)
    # ----------------------------------------------------

    def get_recent_decisions(self, limit: int = 50) -> List[PolicyDecision]:
        path = self.paths["audit_log"]
        if not os.path.exists(path):
            return []

        decisions: List[PolicyDecision] = []

        with open(path, "r") as f:
            lines = f.readlines()[-limit:]

        for line in lines:
            try:
                entry = json.loads(line)

                # Timestamp (ISO → epoch)
                ts_raw = entry.get("ts_utc")
                ts = (
                    datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
                    if ts_raw else 0.0
                )

                decision_raw = entry.get("decision", "no_action")
                guardrail_reason = entry.get("guardrail_reason")

                # Normalize decision semantics for UI
                if decision_raw == "action":
                    decision = "allow"
                elif guardrail_reason == "blocked":
                    decision = "block"
                else:
                    decision = "no_action"

                # Guardrails
                guardrails = []
                if guardrail_reason:
                    guardrails.append({
                        "name": entry.get("policy", "unknown"),
                        "triggered": guardrail_reason == "blocked",
                    })

                # Recommended actions
                recommended_actions = []
                action_plan = entry.get("action_plan")
                if action_plan:
                    recommended_actions.append(action_plan.get("type"))

                decisions.append(
                    PolicyDecision(
                        ts=ts,
                        policy_id=entry.get("policy", "n/a"),
                        decision=decision,
                        reason=entry.get("reason", guardrail_reason or ""),
                        guardrails=guardrails,
                        recommended_actions=recommended_actions,
                    )
                )
            except Exception as e:
                logger.debug(f"Skipping audit entry: {e}")
                continue

        return sorted(decisions, key=lambda d: d.ts, reverse=True)
