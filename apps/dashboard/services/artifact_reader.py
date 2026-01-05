import json
import os
import logging
from typing import List, Optional
from apps.dashboard.services.dto import (
    AnomalyEvent, 
    RcaReport, 
    PolicyDecision, 
    FeatureSnapshot
)

# Setup Logger
logger = logging.getLogger("dashboard.reader")

class ArtifactReader:
    def __init__(self):
        # 1. Determine Project Root securely
        # This assumes this file is in apps/dashboard/services/
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        dashboard_dir = os.path.dirname(services_dir)
        apps_dir = os.path.dirname(dashboard_dir)
        self.project_root = os.path.dirname(apps_dir)
        
        # 2. Define Paths
        self.paths = {
            "detection": os.path.join(self.project_root, "data", "runtime", "latest_detection.json"),
            "features": os.path.join(self.project_root, "data", "runtime", "latest_features.json"),
            "rca": os.path.join(self.project_root, "data", "runtime", "latest_rca.json"),
            "audit_log": os.path.join(self.project_root, "policy_engine", "audit", "policy_decisions.jsonl")
        }

        # 3. DEBUG: Print paths on startup to verify they are correct
        print(f"--- ARTIFACT READER DEBUG ---")
        print(f"Looking for Detection at: {self.paths['detection']}")
        print(f"File Exists? {os.path.exists(self.paths['detection'])}")
        print(f"-----------------------------")

    def _read_json(self, path: str) -> Optional[dict]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read {path}: {e}")
            return None

    def get_latest_anomaly(self) -> Optional[AnomalyEvent]:
        data = self._read_json(self.paths["detection"])
        if not data:
            return None
        return AnomalyEvent(
            ts=data.get("timestamp", 0.0),
            service=data.get("service", "unknown"),
            score=data.get("anomaly_score", 0.0),
            anomaly_type=data.get("type", "unknown"),
            model=data.get("model_version", "v1"),
            features_ref=data.get("window_id")
        )

    def get_latest_features(self) -> Optional[FeatureSnapshot]:
        data = self._read_json(self.paths["features"])
        if not data:
            return None
        return FeatureSnapshot(
            ts=data.get("timestamp", 0.0),
            window_id=data.get("window_id", "unknown"),
            top_features=data.get("features", [])
        )

    def get_latest_rca(self) -> Optional[RcaReport]:
        data = self._read_json(self.paths["rca"])
        if not data:
            return None
        
        # Handle evidence format differences
        evidence = data.get("evidence", {})
        if isinstance(evidence, list): evidence = {"trace_ids": [], "logs": []}

        return RcaReport(
            ts=data.get("timestamp", 0.0),
            incident_id=data.get("incident_id", "unknown"),
            ranked_causes=data.get("root_causes", []),
            evidence=evidence
        )

    def get_recent_decisions(self, limit: int = 50) -> List[PolicyDecision]:
        path = self.paths["audit_log"]
        if not os.path.exists(path):
            return []

        decisions = []
        try:
            with open(path, 'r') as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    try:
                        entry = json.loads(line)
                        decisions.append(PolicyDecision(
                            ts=entry.get("timestamp", 0.0),
                            policy_id=entry.get("policy_id", "default"),
                            decision=entry.get("decision", "unknown"),
                            reason=entry.get("reason", ""),
                            guardrails=entry.get("guardrails_checked", []),
                            recommended_actions=entry.get("recommendations", [])
                        ))
                    except json.JSONDecodeError:
                        continue
            return sorted(decisions, key=lambda x: x.ts, reverse=True)
        except Exception as e:
            logger.error(f"Error reading audit log: {e}")
            return []