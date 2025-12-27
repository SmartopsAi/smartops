from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import List, Optional

from apps.policy_engine.dsl.parser import parse_policies
from apps.policy_engine.dsl.model import Policy


@dataclass(frozen=True)
class ReloadResult:
    ok: bool
    policy_count: int
    source_path: str
    error: Optional[str] = None


class PolicyStore:
    """
    WHY:
    - Keep policies in memory (single source of truth)
    - Allow safe runtime reload without restarting the server
    """

    def __init__(self, policy_path: str):
        self._policy_path = policy_path
        self._lock = threading.Lock()
        self._policies: List[Policy] = []

    def get_policies(self) -> List[Policy]:
        # WHY: return a copy so caller can't mutate internal list
        with self._lock:
            return list(self._policies)

    def load_initial(self) -> ReloadResult:
        # WHY: load policies once at startup using same safe logic as reload
        return self.reload()

    def reload(self) -> ReloadResult:
        """
        WHY:
        - Parse first (validate DSL)
        - Swap policies only if parse succeeded (atomic update)
        - If parse fails, keep last-known-good policies
        """
        try:
            if not os.path.exists(self._policy_path):
                return ReloadResult(
                    ok=False,
                    policy_count=len(self.get_policies()),
                    source_path=self._policy_path,
                    error=f"Policy file not found: {self._policy_path}",
                )

            with open(self._policy_path, "r", encoding="utf-8") as f:
                text = f.read()

            new_policies = parse_policies(text)

            with self._lock:
                self._policies = list(new_policies)

            return ReloadResult(
                ok=True,
                policy_count=len(new_policies),
                source_path=self._policy_path,
                error=None,
            )

        except Exception as e:
            return ReloadResult(
                ok=False,
                policy_count=len(self.get_policies()),
                source_path=self._policy_path,
                error=str(e),
            )
