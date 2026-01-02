from __future__ import annotations

import time
import os
from datetime import datetime

from apps.policy_engine.repository.policy_store import load_default_policies
from apps.policy_engine.runtime.adapter import load_runtime_signals
from apps.policy_engine.runtime.evaluator import evaluate_policies
from apps.policy_engine.runtime.guardrails import apply_guardrails

# Must match your app.py default target
DEFAULT_TARGET = {
    "kind": "Deployment",
    "namespace": "smartops-dev",
    "name": "erp-simulator",
}


def utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def build_action_plan(chosen) -> dict:
    if chosen.action.type == "restart":
        return {
            "type": "restart",
            "dry_run": False,
            "verify": True,
            "target": DEFAULT_TARGET,
        }
    return {
        "type": "scale",
        "dry_run": False,
        "verify": True,
        "target": DEFAULT_TARGET,
        "scale": {"replicas": chosen.action.replicas},
    }


def print_report(decision: dict) -> None:
    # clear screen (optional) so it looks like a live dashboard in terminal
    # comment these two lines if you prefer scrolling logs.
    # os.system("cls" if os.name == "nt" else "clear")

    print("===== POLICY ENGINE DECISION REPORT =====")
    print(f"Time (UTC):        {decision.get('ts_utc', 'N/A')}")
    print(f"Decision:          {decision.get('decision', 'N/A')}")

    if decision.get("decision") == "no_action":
        print(f"Reason:            {decision.get('reason', 'N/A')}")
        sig = decision.get("signal_summary") or {}
        if sig:
            print("\nSignal Summary:")
            for k, v in sig.items():
                print(f"  - {k}: {v}")

        print("=========================================")
        return

    # action / blocked
    print(f"Policy:            {decision.get('policy', 'N/A')}")
    print(f"Priority:          {decision.get('priority', 'N/A')}")
    print(f"Guardrail Reason:  {decision.get('guardrail_reason', 'N/A')}")

    ap = decision.get("action_plan") or {}
    if ap:
        print(f"Action Type:       {ap.get('type', 'N/A')}")
        print(f"Dry Run:           {ap.get('dry_run', 'N/A')}")
        print(f"Verify:            {ap.get('verify', 'N/A')}")

        tgt = ap.get("target") or {}
        print(
            f"Target:            {tgt.get('kind','?')} / {tgt.get('namespace','?')} / {tgt.get('name','?')}"
        )

        if ap.get("type") == "scale":
            scale = ap.get("scale") or {}
            print(f"Scale Replicas:    {scale.get('replicas', 'N/A')}")

    sig = decision.get("signal_summary") or {}
    if sig:
        print("\nSignal Summary:")
        for k, v in sig.items():
            print(f"  - {k}: {v}")

    print("=========================================")


def evaluate_once() -> dict:
    policies = load_default_policies()
    signal = load_runtime_signals()

    anomaly_flag = bool(signal["raw"]["detection"].get("anomaly", False))

    if not anomaly_flag:
        return {
            "ts_utc": utc_now(),
            "decision": "no_action",
            "reason": "no active anomaly",
            "signal_summary": {
                "anomaly.type": signal.get("anomaly.type"),
                "rca.cause": signal.get("rca.cause"),
            },
        }

    chosen = evaluate_policies(policies, signal)

    if not chosen:
        return {
            "ts_utc": utc_now(),
            "decision": "no_action",
            "reason": "no policy matched",
            "signal_summary": {
                "anomaly.type": signal.get("anomaly.type"),
                "rca.cause": signal.get("rca.cause"),
            },
        }

    action_plan = build_action_plan(chosen)
    allowed, reason = apply_guardrails(action_plan)

    return {
        "ts_utc": utc_now(),
        "decision": "action" if allowed else "blocked",
        "policy": chosen.name,
        "priority": chosen.priority,
        "guardrail_reason": reason,
        "action_plan": action_plan if allowed else None,
        "signal_summary": {
            "anomaly.type": signal.get("anomaly.type"),
            "anomaly.score": signal.get("anomaly.score"),
            "rca.cause": signal.get("rca.cause"),
            "rca.probability": signal.get("rca.probability"),
        },
    }


def main(poll_seconds: int = 3) -> None:
    last_fingerprint = None

    while True:
        try:
            decision = evaluate_once()

            # Only re-print when something changes (reduces flicker)
            fingerprint = (
                decision.get("decision"),
                decision.get("policy"),
                decision.get("guardrail_reason"),
                json_safe(decision.get("action_plan")),
                json_safe(decision.get("signal_summary")),
            )
            if fingerprint != last_fingerprint:
                print_report(decision)
                last_fingerprint = fingerprint

        except Exception as e:
            # If something breaks, show it clearly
            os.system("cls" if os.name == "nt" else "clear")
            print("===== POLICY ENGINE WATCH ERROR =====")
            print(repr(e))
            print("=====================================")

        time.sleep(poll_seconds)


def json_safe(obj):
    # Simple stable conversion for fingerprint comparisons
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return tuple(sorted((k, json_safe(v)) for k, v in obj.items()))
    if isinstance(obj, list):
        return tuple(json_safe(x) for x in obj)
    return str(obj)


if __name__ == "__main__":
    main(poll_seconds=2)
