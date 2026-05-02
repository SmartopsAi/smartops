from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

ADMIN_KEY_ENV = "SMARTOPS_ADMIN_API_KEY"
ADMIN_KEY_HEADER = "X-SmartOps-Admin-Key"


def _expected_admin_key() -> str:
    return os.getenv(ADMIN_KEY_ENV, "").strip()


def is_admin_configured() -> bool:
    return bool(_expected_admin_key())


def require_admin_key(request: Request) -> None:
    expected = _expected_admin_key()
    if not expected:
        raise HTTPException(status_code=503, detail="Admin API key is not configured.")

    provided = request.headers.get(ADMIN_KEY_HEADER, "")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing admin API key.")
