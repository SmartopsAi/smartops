from __future__ import annotations

import os
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DASHBOARD_API_URL_ENV = "DASHBOARD_API_URL"
ADMIN_KEY_ENV = "SMARTOPS_ADMIN_API_KEY"
UNMATCHED_TRIGGER_PATH = "/api/notifications/triggers/unmatched-anomaly"


def _dashboard_url() -> str:
    return os.getenv(DASHBOARD_API_URL_ENV, "").rstrip("/")


def notify_unmatched_anomaly(record: dict[str, Any], reason: str = "no policy matched") -> dict[str, Any]:
    dashboard_url = _dashboard_url()
    admin_key = os.getenv(ADMIN_KEY_ENV, "")

    if not dashboard_url:
        return {
            "attempted": False,
            "sent": False,
            "status": "skipped",
            "message": "DASHBOARD_API_URL is not configured.",
        }

    if not admin_key:
        return {
            "attempted": False,
            "sent": False,
            "status": "skipped",
            "message": "SMARTOPS_ADMIN_API_KEY is not configured.",
        }

    try:
        request = Request(
            f"{dashboard_url}{UNMATCHED_TRIGGER_PATH}",
            data=json.dumps(
                {
                    "unmatched_anomaly": record,
                    "source": "policy-engine",
                    "reason": reason,
                }
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-SmartOps-Admin-Key": admin_key,
            },
            method="POST",
        )
        with urlopen(request, timeout=5) as response:  # noqa: S310 - URL is operator-configured internal service.
            status_code = response.getcode()
            raw_body = response.read().decode("utf-8", errors="ignore")
    except HTTPError as exc:
        return {
            "attempted": True,
            "sent": False,
            "status": "failed",
            "message": f"Dashboard trigger returned HTTP {exc.code}.",
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "attempted": True,
            "sent": False,
            "status": "failed",
            "message": f"Dashboard notification trigger failed: {exc.__class__.__name__}.",
        }

    try:
        payload = json.loads(raw_body or "{}")
    except Exception:
        payload = {}

    if 200 <= status_code < 300:
        status = payload.get("status") or "sent"
        return {
            "attempted": True,
            "sent": bool(payload.get("sent")),
            "status": status,
            "message": payload.get("message") or f"Dashboard trigger returned HTTP {status_code}.",
        }

    return {
        "attempted": True,
        "sent": False,
        "status": "failed",
        "message": f"Dashboard trigger returned HTTP {status_code}.",
    }
