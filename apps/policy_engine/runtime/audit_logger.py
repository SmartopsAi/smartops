from __future__ import annotations

import json
import os
from typing import Any, Dict, List


class AuditLogger:
    """
    WHY:
    - Central place to write + read audit events
    - Keeps app.py clean
    - JSONL format: one JSON per line
    """

    def __init__(self, log_path: str):
        self.log_path = log_path
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def write_event(self, event: Dict[str, Any]) -> None:
        """
        WHY:
        - Append-only logging (safe)
        - Each request adds one line
        """
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def read_last_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        WHY:
        - Used by /v1/policy/audit
        - Return most recent N audit events
        - Reads safely even if file is big
        """
        if not os.path.exists(self.log_path):
            return []

        # Simple approach (OK for your project size):
        # read all lines then take last N
        # If file becomes huge, we can optimize later.
        with open(self.log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        lines = lines[-limit:]

        events: List[Dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                # skip bad lines instead of crashing
                continue

        return events
