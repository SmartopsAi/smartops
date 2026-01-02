from pathlib import Path
from apps.policy_engine.dsl.parser import parse_policies

DEFAULT_POLICY_PATH = Path("apps/policy_engine/policies/default.policy")

def load_default_policies():
    text = DEFAULT_POLICY_PATH.read_text(encoding="utf-8")
    return parse_policies(text)
