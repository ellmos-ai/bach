# SPDX-License-Identifier: MIT
"""Private factory provenance for a concrete native HTTP backend instance.

Neither provider output nor task/slot JSON can manufacture this seal. Secrets
stay in process memory and are never hashed, serialized or returned.
"""
from __future__ import annotations

import hashlib
import json
import weakref
from urllib.parse import urlsplit, urlunsplit

_SEAL = object()
_CREDENTIAL_REFS = {
    "openai": {"env:OPENAI_API_KEY", "file:openai_api_key"},
    "claude-api": {"env:ANTHROPIC_API_KEY", "file:anthropic_api_key"},
    "hermes": {"env:OPENROUTER_API_KEY", "file:openrouter_api_key", "credentials_dir:openrouter.env:OPENROUTER_API_KEY"},
    "openrouter": {"env:OPENROUTER_API_KEY", "file:openrouter_api_key", "credentials_dir:openrouter.env:OPENROUTER_API_KEY"},
}


class _ControllerRoute:
    __slots__ = ("backend", "kind", "origin", "credential", "key", "seal")

    def __init__(self, backend, kind, origin, credential, *, seal):
        if seal is not _SEAL:
            raise ValueError("Private Controllerroute erforderlich")
        self.backend = weakref.ref(backend)
        self.kind, self.origin, self.credential = kind, origin, credential
        self.key = getattr(backend, "api_key", None)
        self.seal = seal

    def __repr__(self):
        return "<ControllerRoute private>"


def _origin(backend, kind):
    raw = getattr(backend, "base_url", None)
    if kind == "claude-api":
        raw = "https://api.anthropic.com/v1"
    if (type(raw) is not str or len(raw) > 2048 or raw != raw.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in raw)):
        return None
    try:
        parts = urlsplit(raw)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username is not None or parts.password is not None
                or parts.query or parts.fragment):
            return None
        # Canonicalize host and default port, retaining path case and IPv6.
        host = parts.hostname.lower()
        if ":" in host:
            host = "[" + host + "]"
        port = parts.port
        if port is not None and port != (443 if parts.scheme == "https" else 80):
            host += ":" + str(port)
        return urlunsplit((parts.scheme, host, parts.path.rstrip("/"), "", ""))
    except ValueError:
        return None


def bind_controller_backend(backend, *, credential_ref=None):
    """Called by the native factory, never with a request's claimed principal."""
    from .model_backend import backend_identifier
    kind = backend_identifier(backend)
    origin = _origin(backend, kind)
    if kind not in {"ollama", "lmstudio", "openai", "claude-api", "hermes", "openrouter"} or origin is None:
        return backend
    if kind in {"ollama", "lmstudio"}:
        credential = "native-runtime:" + kind
    elif (type(credential_ref) is str and credential_ref in _CREDENTIAL_REFS.get(kind, ())
          and getattr(backend, "api_key", None)):
        credential = credential_ref
    else:
        return backend
    backend._controller_route = _ControllerRoute(backend, kind, origin, credential, seal=_SEAL)
    return backend


def route_snapshot(backend):
    stamp = getattr(backend, "_controller_route", None)
    if (not isinstance(stamp, _ControllerRoute) or stamp.seal is not _SEAL
            or stamp.backend() is not backend or _origin(backend, stamp.kind) != stamp.origin
            or getattr(backend, "api_key", None) != stamp.key):
        return None
    value = {"backend_id": stamp.kind, "origin": stamp.origin,
             "credential_ref": stamp.credential}
    digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"backend_id": stamp.kind, "route_sha256": digest}
