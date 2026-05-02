from __future__ import annotations

import os
import re
from typing import Any

import requests

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_MODEL_ENV = "OPENAI_MODEL"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class PolicyDraftAIError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _display(value: Any, fallback: str = "unknown") -> str:
    if value is None or value == "":
        return fallback
    return str(value)


def build_policy_prompt(unmatched_anomaly: dict[str, Any], constraints: dict[str, Any] | None = None) -> str:
    constraints = constraints or {}
    preferred_action = constraints.get("preferred_action", "auto")
    max_replicas = constraints.get("max_replicas", 4)

    return f"""
Generate one SmartOps policy DSL draft for human review.

Return DSL only. Do not use markdown fences. Do not include explanations.

Current SmartOps DSL grammar examples:
POLICY "policy_name":
  WHEN anomaly.type == "resource"
       AND anomaly.score >= 0.9
  THEN scale(service, 4)
  PRIORITY 120

POLICY "policy_name":
  WHEN anomaly.type == "error"
       AND anomaly.score >= 0.9
  THEN restart(service)
  PRIORITY 250

Allowed actions only:
- scale(service, N), where N is an integer between 1 and 6
- restart(service)

Safety constraints:
- Never generate Kubernetes namespace/deployment direct actions.
- Never generate delete, patch, exec, shell, database, or credential actions.
- Prefer conservative policies.
- Include anomaly.type and anomaly.score conditions.
- Use RCA cause only when it is available and not unknown.
- Avoid unsupported fields when uncertain.
- Priority must be between 100 and 250.
- If scaling, do not exceed max_replicas={max_replicas}.
- preferred_action={preferred_action}

Unmatched anomaly:
- id: {_display(unmatched_anomaly.get("id"))}
- service: {_display(unmatched_anomaly.get("service"))}
- anomaly_type: {_display(unmatched_anomaly.get("anomaly_type"))}
- score: {_display(unmatched_anomaly.get("score"))}
- risk: {_display(unmatched_anomaly.get("risk"))}
- rca_cause: {_display(unmatched_anomaly.get("rca_cause"))}
- rca_probability: {_display(unmatched_anomaly.get("rca_probability"))}
- count: {_display(unmatched_anomaly.get("count"))}
""".strip()


def extract_dsl_from_model_output(text: str) -> str:
    cleaned = str(text or "").strip()
    fence_match = re.search(r"```(?:[a-zA-Z0-9_-]+)?\s*(.*?)```", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    policy_match = re.search(r'(POLICY\s+"[^"]+"\s*:.*)', cleaned, flags=re.DOTALL)
    if policy_match:
        cleaned = policy_match.group(1).strip()

    return cleaned


def _extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]

    output = payload.get("output")
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            content = item.get("content") if isinstance(item, dict) else None
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "\n".join(parts)

    return ""


def generate_policy_draft(
    unmatched_anomaly: dict[str, Any],
    constraints: dict[str, Any] | None = None,
) -> dict[str, str]:
    api_key = os.getenv(OPENAI_API_KEY_ENV, "").strip()
    if not api_key:
        raise PolicyDraftAIError(503, "OPENAI_API_KEY is not configured.")

    model = os.getenv(OPENAI_MODEL_ENV, DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL
    prompt = build_policy_prompt(unmatched_anomaly, constraints)

    try:
        resp = requests.post(
            OPENAI_RESPONSES_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": [
                    {
                        "role": "system",
                        "content": (
                            "You generate only SmartOps policy DSL drafts. "
                            "The DSL must be reviewed and validated before use."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        raise PolicyDraftAIError(502, f"OpenAI policy draft generation failed: {exc}") from exc

    draft_dsl = extract_dsl_from_model_output(_extract_response_text(payload))
    if not draft_dsl:
        raise PolicyDraftAIError(502, "OpenAI returned an empty policy draft.")

    return {
        "draft_dsl": draft_dsl,
        "model": model,
    }
