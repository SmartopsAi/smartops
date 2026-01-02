from datetime import datetime, timedelta

MIN_REPLICAS = 1
MAX_REPLICAS = 10
RESTART_COOLDOWN_SECONDS = 120

_last_restart_at: dict[str, datetime] = {}

def apply_guardrails(action_plan: dict) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    """
    a_type = action_plan.get("type")

    if a_type == "scale":
        replicas = action_plan.get("scale", {}).get("replicas")
        if replicas is None:
            return False, "scale.replicas missing"

        if replicas < MIN_REPLICAS or replicas > MAX_REPLICAS:
            return False, f"replicas {replicas} out of bounds [{MIN_REPLICAS}, {MAX_REPLICAS}]"

    if a_type == "restart":
        t = action_plan.get("target", {})
        key = f"{t.get('namespace','')}/{t.get('name','')}"
        now = datetime.utcnow()
        last = _last_restart_at.get(key)
        if last and (now - last) < timedelta(seconds=RESTART_COOLDOWN_SECONDS):
            return False, f"restart cooldown active ({RESTART_COOLDOWN_SECONDS}s)"
        _last_restart_at[key] = now

    return True, "allowed"
