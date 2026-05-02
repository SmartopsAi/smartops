from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

SETTINGS_ENV = "NOTIFICATION_SETTINGS_PATH"
AUDIT_ENV = "NOTIFICATION_AUDIT_PATH"
DEFAULT_SETTINGS_PATH = "/policy_engine/store/notification_settings.json"
DEFAULT_AUDIT_PATH = "/policy_engine/store/notification_audit.jsonl"
FALLBACK_DIR = Path("/tmp/smartops-notifications")
SECRET_KEYS = {
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "auth_token",
    "smtp_password",
    "twilio_auth_token",
}


class NotificationServiceError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _path_from_env(env_name: str, default: str, fallback_name: str) -> Path:
    configured = Path(os.getenv(env_name, default))
    try:
        configured.parent.mkdir(parents=True, exist_ok=True)
        test_path = configured.parent / ".smartops-write-test"
        test_path.write_text("ok", encoding="utf-8")
        test_path.unlink(missing_ok=True)
        return configured
    except Exception:
        FALLBACK_DIR.mkdir(parents=True, exist_ok=True)
        return FALLBACK_DIR / fallback_name


def get_settings_path() -> Path:
    return _path_from_env(SETTINGS_ENV, DEFAULT_SETTINGS_PATH, "notification_settings.json")


def get_audit_path() -> Path:
    return _path_from_env(AUDIT_ENV, DEFAULT_AUDIT_PATH, "notification_audit.jsonl")


def _default_settings() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "channels": {
            "email": {
                "enabled": False,
                "provider": "gmail_smtp",
                "mode": "mock",
            },
            "whatsapp": {
                "enabled": False,
                "provider": "twilio_whatsapp",
                "mode": "mock",
            },
            "dashboard": {
                "enabled": True,
                "mode": "internal",
            },
        },
        "recipients": [
            {
                "id": "operator-primary",
                "name": "Primary Operator",
                "role": "Operator",
                "email": "operator@example.com",
                "whatsapp": "+94000000000",
                "enabled": True,
                "channels": ["dashboard"],
                "alert_types": [
                    "HIGH_RISK",
                    "POLICY_BLOCKED",
                    "VERIFICATION_FAILED",
                    "UNMATCHED_ANOMALY",
                ],
            }
        ],
        "rules": {
            "high_or_critical_anomaly": True,
            "policy_blocked": True,
            "verification_failed": True,
            "unmatched_anomaly": True,
            "p1_priority": True,
        },
        "updated_at": _utc_now(),
        "updated_by": "system",
    }


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key.lower() in SECRET_KEYS:
                continue
            redacted[key] = _redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _merge_settings(payload: dict[str, Any], updated_by: str) -> dict[str, Any]:
    current = get_notification_settings()
    merged = {
        **current,
        "channels": {
            **(current.get("channels") or {}),
            **(payload.get("channels") or {}),
        },
        "recipients": payload.get("recipients", current.get("recipients", [])),
        "rules": {
            **(current.get("rules") or {}),
            **(payload.get("rules") or {}),
        },
        "updated_at": _utc_now(),
        "updated_by": updated_by,
    }
    return _redact_secrets(merged)


def get_notification_settings() -> dict[str, Any]:
    path = get_settings_path()
    if not path.exists():
        settings = _default_settings()
        settings["storage_path"] = str(path)
        return settings

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = _default_settings()

    data = _redact_secrets(data)
    data["storage_path"] = str(path)
    return data


def save_notification_settings(payload: dict[str, Any], updated_by: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise NotificationServiceError(400, "Settings payload must be a JSON object.")

    settings = _merge_settings(payload, updated_by)
    path = get_settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except Exception as exc:
        raise NotificationServiceError(500, f"Failed to save notification settings: {exc}") from exc

    append_notification_audit(
        {
            "operation": "settings_update",
            "updated_by": updated_by,
            "channels": list((settings.get("channels") or {}).keys()),
            "recipient_count": len(settings.get("recipients") or []),
            "alert_type": "SETTINGS",
            "status": "mocked",
            "message": "Notification settings updated without storing secrets.",
        }
    )
    return settings


def append_notification_audit(event: dict[str, Any]) -> dict[str, Any]:
    audit_path = get_audit_path()
    audit_event = {
        "ts_utc": _utc_now(),
        "operation": event.get("operation", "mock_send"),
        "updated_by": event.get("updated_by", "operator"),
        "channels": event.get("channels", []),
        "recipient_count": event.get("recipient_count", 0),
        "alert_type": event.get("alert_type", "UNKNOWN"),
        "status": event.get("status", "mocked"),
        "message": event.get("message", ""),
    }

    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_redact_secrets(audit_event), sort_keys=True) + "\n")
    except Exception as exc:
        raise NotificationServiceError(500, f"Failed to append notification audit: {exc}") from exc

    return audit_event


def list_notification_audit(limit: int = 50) -> dict[str, Any]:
    audit_path = get_audit_path()
    events = []
    if audit_path.exists():
        try:
            lines = audit_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            lines = []
        for line in lines[-max(1, limit) :]:
            try:
                events.append(json.loads(line))
            except Exception:
                continue

    return {
        "status": "ok",
        "audit_path": str(audit_path),
        "count": len(events),
        "events": events,
    }


def build_notification_preview(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_notification_settings()
    requested_channels = payload.get("channels") or ["dashboard"]
    recipients = settings.get("recipients") or []
    requested_recipient_ids = set(payload.get("recipient_ids") or [])
    if requested_recipient_ids:
        recipients = [item for item in recipients if item.get("id") in requested_recipient_ids]
    recipients = [item for item in recipients if item.get("enabled", True)]

    return {
        "alert_type": payload.get("alert_type", "TEST"),
        "severity": payload.get("severity", "INFO"),
        "title": payload.get("title", "SmartOps notification"),
        "message": payload.get("message", "SmartOps notification preview"),
        "window_id": payload.get("window_id"),
        "service": payload.get("service"),
        "channels": requested_channels,
        "recipients": recipients,
    }


def send_email_mock(preview: dict[str, Any]) -> dict[str, Any]:
    return {"channel": "email", "mode": "mock", "sent": False, "recipient_count": len(preview["recipients"])}


def send_whatsapp_mock(preview: dict[str, Any]) -> dict[str, Any]:
    return {"channel": "whatsapp", "mode": "mock", "sent": False, "recipient_count": len(preview["recipients"])}


def send_dashboard_mock(preview: dict[str, Any]) -> dict[str, Any]:
    return {"channel": "dashboard", "mode": "mock", "sent": False, "recipient_count": len(preview["recipients"])}


def mock_send_notification(payload: dict[str, Any], updated_by: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise NotificationServiceError(400, "Notification payload must be a JSON object.")

    preview = build_notification_preview(payload)
    channel_results = []
    for channel in preview["channels"]:
        if channel == "email":
            channel_results.append(send_email_mock(preview))
        elif channel == "whatsapp":
            channel_results.append(send_whatsapp_mock(preview))
        elif channel == "dashboard":
            channel_results.append(send_dashboard_mock(preview))
        else:
            channel_results.append({"channel": channel, "mode": "mock", "sent": False, "status": "skipped"})

    audit = append_notification_audit(
        {
            "operation": payload.get("operation", "mock_send"),
            "updated_by": updated_by,
            "channels": preview["channels"],
            "recipient_count": len(preview["recipients"]),
            "alert_type": preview["alert_type"],
            "status": "mocked",
            "message": preview["message"],
        }
    )

    return {
        "status": "ok",
        "mode": "mock",
        "sent": False,
        "mocked": True,
        "preview": preview,
        "channel_results": channel_results,
        "audit": audit,
        "message": "Notification mocked; real providers not enabled in this phase.",
    }
