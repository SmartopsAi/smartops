from __future__ import annotations

import hmac
import os

ADMIN_KEY_ENV = "SMARTOPS_ADMIN_API_KEY"
ADMIN_KEY_HEADER = "X-SmartOps-Admin-Key"


class AdminAuthError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _expected_admin_key() -> str:
    return os.getenv(ADMIN_KEY_ENV, "").strip()


def is_admin_configured() -> bool:
    return bool(_expected_admin_key())


def require_admin_key_from_request(request) -> None:
    expected = _expected_admin_key()
    if not expected:
        raise AdminAuthError(503, "Admin API key is not configured.")

    provided = request.headers.get(ADMIN_KEY_HEADER, "")
    if not provided or not hmac.compare_digest(provided, expected):
        raise AdminAuthError(401, "Invalid or missing admin API key.")


def get_admin_headers_from_request(request) -> dict[str, str]:
    require_admin_key_from_request(request)
    return {ADMIN_KEY_HEADER: request.headers.get(ADMIN_KEY_HEADER, "")}
