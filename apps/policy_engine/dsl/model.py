from dataclasses import dataclass
from typing import List, Any, Optional


@dataclass
class Condition:
    """
    Represents one condition in a policy, e.g.
    anomaly.type == "latency"
    rca.cause == "memory_leak"
    anomaly.score > 0.85
    """
    field: str   # e.g. "anomaly.type", "rca.cause", "anomaly.score"
    op: str      # one of "==", ">", "<", ">=", "<="
    value: Any   # string or number


@dataclass
class Action:
    """
    Represents the action part, e.g.
    restart(service)
    scale(service, 6)
    """
    kind: str                    # "restart" or "scale"
    scale_replicas: Optional[int] = None  # used only for "scale"


@dataclass
class Policy:
    """
    Represents one complete policy with:
      - name: "restart_on_memory_leak"
      - list of conditions
      - exactly one action
    """
    name: str
    conditions: List[Condition]
    action: Action
