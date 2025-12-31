from dataclasses import dataclass
from typing import List, Union

@dataclass
class Condition:
    field: str
    op: str
    value: Union[str, float, int]

@dataclass
class Action:
    type: str  # "restart" | "scale"
    replicas: int | None = None

@dataclass
class Policy:
    name: str
    conditions: List[Condition]
    action: Action
    priority: int
