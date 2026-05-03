from __future__ import annotations

import json
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

try:
    import requests
except Exception:  # pragma: no cover - runtime dependency is provided by the dashboard image.
    requests = None

SETTINGS_ENV = "NOTIFICATION_SETTINGS_PATH"
AUDIT_ENV = "NOTIFICATION_AUDIT_PATH"
DEFAULT_SETTINGS_PATH = "/policy_engine/store/notification_settings.json"
DEFAULT_AUDIT_PATH = "/policy_engine/store/notification_audit.jsonl"
FALLBACK_DIR = Path("/tmp/smartops-notifications")
EMAIL_PROVIDER_ENV = "EMAIL_PROVIDER"
EMAIL_PROVIDERS = {"smtp", "sendgrid"}
SENDGRID_API_URL_DEFAULT = "https://api.sendgrid.com/v3/mail/send"
TWILIO_API_BASE_DEFAULT = "https://api.twilio.com/2010-04-01"
SMTP_ENV_KEYS = {
    "host": "SMTP_HOST",
    "port": "SMTP_PORT",
    "username": "SMTP_USERNAME",
    "password": "SMTP_PASSWORD",
    "from_email": "SMTP_FROM_EMAIL",
}
SECRET_KEYS = {
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "sendgrid_api_key",
    "auth_token",
    "smtp_password",
    "smtp_username",
    "twilio_auth_token",
    "username",
}


class NotificationServiceError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _smtp_config() -> dict[str, Any]:
    values = {key: os.getenv(env_name) for key, env_name in SMTP_ENV_KEYS.items()}
    missing = [env_name for key, env_name in SMTP_ENV_KEYS.items() if not values.get(key)]
    if missing:
        raise NotificationServiceError(
            503,
            "SMTP configuration is incomplete. Missing: " + ", ".join(sorted(missing)),
        )

    try:
        port = int(str(values["port"]))
    except ValueError as exc:
        raise NotificationServiceError(503, "SMTP_PORT must be an integer.") from exc

    return {
        **values,
        "port": port,
        "use_tls": _env_bool("SMTP_USE_TLS", default=True),
    }


def _email_provider() -> str:
    provider = os.getenv(EMAIL_PROVIDER_ENV, "smtp").strip().lower()
    if provider not in EMAIL_PROVIDERS:
        return "smtp"
    return provider


def _sendgrid_config() -> dict[str, str]:
    values = {
        "api_key": os.getenv("SENDGRID_API_KEY"),
        "from_email": os.getenv("SENDGRID_FROM_EMAIL"),
        "api_url": os.getenv("SENDGRID_API_URL", SENDGRID_API_URL_DEFAULT),
    }
    missing = [
        name
        for key, name in {"api_key": "SENDGRID_API_KEY", "from_email": "SENDGRID_FROM_EMAIL"}.items()
        if not values.get(key)
    ]
    if missing:
        raise NotificationServiceError(
            503,
            "SendGrid configuration is incomplete. Missing: " + ", ".join(sorted(missing)),
        )
    return values


def _twilio_config() -> dict[str, str]:
    values = {
        "account_sid": os.getenv("TWILIO_ACCOUNT_SID"),
        "auth_token": os.getenv("TWILIO_AUTH_TOKEN"),
        "from_whatsapp": os.getenv("TWILIO_WHATSAPP_FROM"),
        "fallback_to": os.getenv("TWILIO_WHATSAPP_TO"),
        "api_base": os.getenv("TWILIO_API_BASE", TWILIO_API_BASE_DEFAULT).rstrip("/"),
    }
    missing = [
        name
        for key, name in {
            "account_sid": "TWILIO_ACCOUNT_SID",
            "auth_token": "TWILIO_AUTH_TOKEN",
            "from_whatsapp": "TWILIO_WHATSAPP_FROM",
        }.items()
        if not values.get(key)
    ]
    if missing:
        raise NotificationServiceError(
            503,
            "Twilio configuration is incomplete. Missing: " + ", ".join(sorted(missing)),
        )
    return values


def _redact_error(message: str) -> str:
    redacted = message
    secret_env_names = list(SMTP_ENV_KEYS.values()) + ["SENDGRID_API_KEY", "TWILIO_AUTH_TOKEN"]
    for env_name in secret_env_names:
        value = os.getenv(env_name)
        if value:
            redacted = redacted.replace(value, "[redacted]")
    return redacted


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


def _email_recipients(preview: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        recipient
        for recipient in preview["recipients"]
        if recipient.get("enabled", True)
        and recipient.get("email")
        and "email" in (recipient.get("channels") or [])
    ]


def _email_subject(preview: dict[str, Any]) -> str:
    if preview.get("alert_type") == "TEST":
        return "SmartOps Test Notification"

    severity = preview.get("severity") or "INFO"
    title = preview.get("title") or "SmartOps notification"
    return f"[SmartOps] {severity} - {title}"


def _email_body(preview: dict[str, Any]) -> str:
    fields = [
        ("Title", preview.get("title") or "SmartOps notification"),
        ("Message", preview.get("message") or "SmartOps notification"),
        ("Alert type", preview.get("alert_type") or "UNKNOWN"),
        ("Severity", preview.get("severity") or "INFO"),
        ("Service", preview.get("service") or "Not available"),
        ("Window ID", preview.get("window_id") or "Not available"),
        ("Timestamp", _utc_now()),
    ]
    lines = [f"{label}: {value}" for label, value in fields]
    lines.extend(
        [
            "",
            "This message was generated by SmartOps notification routing.",
        ]
    )
    return "\n".join(lines)


def send_email_mock(preview: dict[str, Any]) -> dict[str, Any]:
    return {"channel": "email", "mode": "mock", "sent": False, "recipient_count": len(preview["recipients"])}


def send_email_real(payload: dict[str, Any], recipients: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    del settings
    preview_recipients = {"recipients": recipients}
    email_recipients = _email_recipients(preview_recipients)
    if not email_recipients:
        return {
            "channel": "email",
            "provider": "smtp",
            "mode": "real",
            "sent": False,
            "recipient_count": 0,
            "error": "No enabled email recipients are configured for the email channel.",
        }

    try:
        config = _smtp_config()
    except NotificationServiceError as exc:
        return {
            "channel": "email",
            "provider": "smtp",
            "mode": "real",
            "sent": False,
            "recipient_count": len(email_recipients),
            "error": exc.message,
        }

    preview = build_notification_preview(payload)
    preview["recipients"] = recipients

    message = EmailMessage()
    message["Subject"] = _email_subject(preview)
    message["From"] = str(config["from_email"])
    message["To"] = ", ".join(str(recipient["email"]) for recipient in email_recipients)
    message.set_content(_email_body(preview))

    try:
        with smtplib.SMTP(str(config["host"]), int(config["port"]), timeout=15) as server:
            if config["use_tls"]:
                server.starttls()
            server.login(str(config["username"]), str(config["password"]))
            server.send_message(message)
    except Exception as exc:
        return {
            "channel": "email",
            "provider": "smtp",
            "mode": "real",
            "sent": False,
            "recipient_count": len(email_recipients),
            "error": _redact_error(str(exc) or exc.__class__.__name__),
        }

    return {
        "channel": "email",
        "provider": "smtp",
        "mode": "real",
        "sent": True,
        "recipient_count": len(email_recipients),
    }


def send_email_sendgrid_real(payload: dict[str, Any], recipients: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    del settings
    preview_recipients = {"recipients": recipients}
    email_recipients = _email_recipients(preview_recipients)
    if not email_recipients:
        return {
            "channel": "email",
            "provider": "sendgrid",
            "mode": "real",
            "sent": False,
            "recipient_count": 0,
            "error": "No enabled email recipients are configured for the email channel.",
        }

    try:
        config = _sendgrid_config()
    except NotificationServiceError as exc:
        return {
            "channel": "email",
            "provider": "sendgrid",
            "mode": "real",
            "sent": False,
            "recipient_count": len(email_recipients),
            "error": exc.message,
        }

    if requests is None:
        return {
            "channel": "email",
            "provider": "sendgrid",
            "mode": "real",
            "sent": False,
            "recipient_count": len(email_recipients),
            "error": "The requests package is unavailable in this runtime.",
        }

    preview = build_notification_preview(payload)
    preview["recipients"] = recipients
    request_body = {
        "personalizations": [
            {
                "to": [{"email": str(recipient["email"])} for recipient in email_recipients],
                "subject": _email_subject(preview),
            }
        ],
        "from": {"email": str(config["from_email"])},
        "content": [
            {
                "type": "text/plain",
                "value": _email_body(preview),
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(str(config["api_url"]), headers=headers, json=request_body, timeout=15)
    except Exception as exc:
        return {
            "channel": "email",
            "provider": "sendgrid",
            "mode": "real",
            "sent": False,
            "recipient_count": len(email_recipients),
            "error": _redact_error(str(exc) or exc.__class__.__name__),
        }

    if not 200 <= int(response.status_code) < 300:
        response_text = _redact_error((getattr(response, "text", "") or "").strip())
        safe_error = f"SendGrid returned HTTP {response.status_code}."
        if response_text:
            safe_error = f"{safe_error} {response_text[:300]}"
        return {
            "channel": "email",
            "provider": "sendgrid",
            "mode": "real",
            "sent": False,
            "recipient_count": len(email_recipients),
            "error": safe_error,
        }

    return {
        "channel": "email",
        "provider": "sendgrid",
        "mode": "real",
        "sent": True,
        "recipient_count": len(email_recipients),
    }


def send_whatsapp_mock(preview: dict[str, Any]) -> dict[str, Any]:
    return {"channel": "whatsapp", "mode": "mock", "sent": False, "recipient_count": len(preview["recipients"])}


def _normalize_whatsapp_destination(value: str | None) -> str | None:
    if not value:
        return None
    destination = value.strip()
    if not destination:
        return None
    if destination.startswith("whatsapp:"):
        return destination
    return f"whatsapp:{destination}"


def _whatsapp_recipients(recipients: list[dict[str, Any]], fallback_to: str | None) -> list[str]:
    destinations = []
    fallback = _normalize_whatsapp_destination(fallback_to)
    for recipient in recipients:
        if not recipient.get("enabled", True):
            continue
        if "whatsapp" not in (recipient.get("channels") or []):
            continue
        destination = _normalize_whatsapp_destination(recipient.get("whatsapp")) or fallback
        if destination:
            destinations.append(destination)
    return list(dict.fromkeys(destinations))


def _whatsapp_body(preview: dict[str, Any]) -> str:
    if preview.get("alert_type") == "TEST":
        heading = "SmartOps Test Notification"
    else:
        severity = preview.get("severity") or "INFO"
        title = preview.get("title") or "SmartOps notification"
        heading = f"[SmartOps] {severity} - {title}"

    parts = [
        heading,
        str(preview.get("message") or "SmartOps notification"),
        f"Alert type: {preview.get('alert_type') or 'UNKNOWN'}",
        f"Service: {preview.get('service') or 'Not available'}",
        f"Window ID: {preview.get('window_id') or 'Not available'}",
        f"Timestamp: {_utc_now()}",
        "Generated by SmartOps notification routing.",
    ]
    return "\n".join(parts)[:1400]


def send_whatsapp_twilio_real(payload: dict[str, Any], recipients: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    del settings
    try:
        config = _twilio_config()
    except NotificationServiceError as exc:
        return {
            "channel": "whatsapp",
            "provider": "twilio_whatsapp",
            "mode": "real",
            "sent": False,
            "recipient_count": 0,
            "message_sids": [],
            "error": exc.message,
        }

    destinations = _whatsapp_recipients(recipients, config.get("fallback_to"))
    if not destinations:
        return {
            "channel": "whatsapp",
            "provider": "twilio_whatsapp",
            "mode": "real",
            "sent": False,
            "recipient_count": 0,
            "message_sids": [],
            "error": "No enabled WhatsApp recipients are configured for the WhatsApp channel.",
        }

    if requests is None:
        return {
            "channel": "whatsapp",
            "provider": "twilio_whatsapp",
            "mode": "real",
            "sent": False,
            "recipient_count": len(destinations),
            "message_sids": [],
            "error": "The requests package is unavailable in this runtime.",
        }

    preview = build_notification_preview(payload)
    preview["recipients"] = recipients
    url = f"{config['api_base']}/Accounts/{config['account_sid']}/Messages.json"
    message_sids = []
    sent_count = 0
    errors = []
    for destination in destinations:
        try:
            response = requests.post(
                url,
                auth=(config["account_sid"], config["auth_token"]),
                data={
                    "From": _normalize_whatsapp_destination(config["from_whatsapp"]),
                    "To": destination,
                    "Body": _whatsapp_body(preview),
                },
                timeout=15,
            )
        except Exception as exc:
            errors.append(_redact_error(str(exc) or exc.__class__.__name__))
            continue

        if 200 <= int(response.status_code) < 300:
            sent_count += 1
            try:
                message_sid = (response.json() or {}).get("sid")
            except Exception:
                message_sid = None
            if message_sid:
                message_sids.append(str(message_sid))
            continue

        response_text = _redact_error((getattr(response, "text", "") or "").strip())
        safe_error = f"Twilio returned HTTP {response.status_code}."
        if response_text:
            safe_error = f"{safe_error} {response_text[:300]}"
        errors.append(safe_error)

    result = {
        "channel": "whatsapp",
        "provider": "twilio_whatsapp",
        "mode": "real",
        "sent": sent_count > 0,
        "recipient_count": len(destinations),
        "message_sids": message_sids,
    }
    if errors:
        result["error"] = "; ".join(errors)
    return result


def send_dashboard_mock(preview: dict[str, Any]) -> dict[str, Any]:
    return {"channel": "dashboard", "mode": "mock", "sent": False, "recipient_count": len(preview["recipients"])}


def mock_send_notification(payload: dict[str, Any], updated_by: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise NotificationServiceError(400, "Notification payload must be a JSON object.")

    settings = get_notification_settings()
    preview = build_notification_preview(payload)
    channel_results = []
    real_email_attempted = False
    real_whatsapp_attempted = False
    for channel in preview["channels"]:
        if channel == "email":
            email_settings = ((settings.get("channels") or {}).get("email") or {})
            if email_settings.get("enabled") is True and email_settings.get("mode") == "real":
                real_email_attempted = True
                if _email_provider() == "sendgrid":
                    channel_results.append(send_email_sendgrid_real(payload, preview["recipients"], settings))
                else:
                    channel_results.append(send_email_real(payload, preview["recipients"], settings))
            else:
                channel_results.append(send_email_mock(preview))
        elif channel == "whatsapp":
            whatsapp_settings = ((settings.get("channels") or {}).get("whatsapp") or {})
            if whatsapp_settings.get("enabled") is True and whatsapp_settings.get("mode") == "real":
                real_whatsapp_attempted = True
                channel_results.append(send_whatsapp_twilio_real(payload, preview["recipients"], settings))
            else:
                channel_results.append(send_whatsapp_mock(preview))
        elif channel == "dashboard":
            channel_results.append(send_dashboard_mock(preview))
        else:
            channel_results.append({"channel": channel, "mode": "mock", "sent": False, "status": "skipped"})

    failed = any(result.get("error") for result in channel_results)
    sent = any(result.get("sent") is True for result in channel_results)
    real_provider_attempted = real_email_attempted or real_whatsapp_attempted
    if failed:
        operation = "send_failed"
    elif real_whatsapp_attempted and sent:
        operation = "whatsapp_send"
    elif real_email_attempted:
        operation = "email_send"
    else:
        operation = "mock_send"
    audit_status = "failed" if failed else ("sent" if real_provider_attempted and sent else "mocked")
    audit = append_notification_audit(
        {
            "operation": operation,
            "updated_by": updated_by,
            "channels": preview["channels"],
            "recipient_count": len(preview["recipients"]),
            "alert_type": preview["alert_type"],
            "status": audit_status,
            "message": preview["message"],
        }
    )

    mode = "real" if real_provider_attempted else "mock"
    if failed:
        status = "error"
        response_message = "Notification send failed safely; no secrets were exposed."
    elif real_provider_attempted:
        status = "ok"
        response_message = "Notification sent through configured real provider(s)."
    else:
        status = "ok"
        response_message = "Notification mocked; real providers not enabled in this phase."

    return {
        "status": status,
        "mode": mode,
        "sent": sent,
        "mocked": not real_provider_attempted,
        "preview": preview,
        "channel_results": channel_results,
        "audit": audit,
        "message": response_message,
    }
