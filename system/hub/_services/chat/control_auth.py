"""Authentication helpers for the local BACH Control API.

The bearer value is supplied either through ``BACH_CONTROL_API_TOKEN`` or the
existing OS-keyring-backed BACH secrets store under
``bach_control_api_token``.  No plaintext fallback is used: an unavailable or
empty credential fails closed.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Mapping


CONTROL_API_TOKEN_ENV = "BACH_CONTROL_API_TOKEN"
CONTROL_API_SECRET = "bach_control_api_token"


def get_control_api_token() -> str:
    """Return the configured Control-API token without logging its value."""

    configured = str(os.environ.get(CONTROL_API_TOKEN_ENV) or "").strip()
    if configured:
        return configured

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
