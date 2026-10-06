"""Authentication helpers for the local BACH Control API.

The bearer value comes from ``BACH_CONTROL_API_TOKEN``, an explicitly
configured ``BACH_CONTROL_API_TOKEN_FILE``, or the OS-keyring-backed BACH
secrets store. An unavailable or empty credential fails closed.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping
from pathlib import Path


CONTROL_API_TOKEN_ENV = "BACH_CONTROL_API_TOKEN"
CONTROL_API_TOKEN_FILE_ENV = "BACH_CONTROL_API_TOKEN_FILE"
CONTROL_API_SECRET = "bach_control_api_token"


def get_control_api_token() -> str:
    """Return the configured Control-API token without logging its value."""

    configured = str(os.environ.get(CONTROL_API_TOKEN_ENV) or "").strip()
    if configured:
        return configured

    token_file = str(os.environ.get(CONTROL_API_TOKEN_FILE_ENV) or "").strip()
    if token_file:
        try:
            configured = Path(token_file).read_text(encoding="utf-8").strip()
            if configured:
                return configured
        except (OSError, UnicodeError):
            pass

    default_file = Path.home() / ".credentials" / "bach_control_api_token"
    if default_file.exists():
        try:
            configured = default_file.read_text(encoding="utf-8").strip()
            if configured:
                return configured
        except (OSError, UnicodeError):
            pass

    try:
        from hub.secrets_handler import get_secret_value

        configured = get_secret_value(CONTROL_API_SECRET)
    except Exception:
        # Missing keyring/backend is an authentication failure, not a reason to
        # expose the mutating API without a credential.
        return ""
    return str(configured or "").strip()


def get_control_api_auth_header() -> str:
    """Return the bearer header value for trusted in-process callers."""

    token = get_control_api_token()
    return f"Bearer {token}" if token else ""


def is_control_api_authorized(headers: Mapping[str, str]) -> bool:
    """Validate a request's Bearer header against the configured token."""

    configured = get_control_api_token()
    if not configured:
        return False

    authorization = str(headers.get("Authorization") or "").strip()
    scheme, separator, supplied = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer":
        return False
    supplied = supplied.strip()
    return bool(supplied) and hmac.compare_digest(supplied, configured)
