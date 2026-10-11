# SPDX-License-Identifier: MIT
"""Bounded native metadata reads. Catalog presence is no residency/RAM proof."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx

from .local_provider_config import local_backend_configs
from .model_sockets import socket_id

_MAX_BYTES = 2_000_000
_MAX_MODELS = 64


def _json(client, method, url, *, timeout, deadline, **kwargs):
    with client.stream(method, url, timeout=timeout, **kwargs) as response:
        response.raise_for_status()
        data = bytearray()
        for block in response.iter_bytes():
            if time.monotonic() >= deadline:
                raise ValueError("Metadatenbudget ausgeschöpft")
            data.extend(block)
            if len(data) > _MAX_BYTES:
                raise ValueError("Modellmetadaten überschreiten das Größenlimit")
        import json
        return json.loads(data)


def _positive(value):
    return value if type(value) is int and value > 0 else None


def _item(provider, name, host, metadata, size):
    key = socket_id(provider, name, host)
    if not isinstance(metadata, dict) or metadata.get("remote_host") or metadata.get("remote_model"):
        raise ValueError("Keine bestätigten lokalen Modellmetadaten")
    details, info = metadata.get("details"), metadata.get("model_info")
    capabilities = metadata.get("capabilities")
    if (not isinstance(details, dict) or details.get("format") not in {"gguf", "mlx", "safetensors"}
            or not isinstance(info, dict) or not _positive(info.get("general.parameter_count"))
            or not isinstance(capabilities, list) or not capabilities
            or any(not isinstance(value, str) or len(value) > 80 for value in capabilities)):
        raise ValueError("Lokale Modellfähigkeiten nicht bestätigt")
    return {"socket_id": key, "backend": provider, "model": name, "host_id": host,
            "local_metadata_verified": True, "capabilities": sorted(set(capabilities)),
            "chat_eligible": "completion" in capabilities,
            "native_tools_capable": "tools" in capabilities,
            "artifact_bytes": _positive(size), "parameter_count": info["general.parameter_count"],
            "format": details["format"], "quantization": (
                details.get("quantization_level") if isinstance(details.get("quantization_level"), str)
                and len(details["quantization_level"]) <= 80 else None),
            "runtime_verified": False, "residency": "unknown", "weight_bytes": None,
            "resource_share": None}


def local_model_catalog(*, configs=None, host_id=None):
    """Read configured loopback providers only; never pull, load or start.

    Invoke on the native engine host. Endpoints come from its trusted config,
    not from a browser/client URL. Metadata cannot establish inference success.
    """
    import platform
    host = platform.node() if host_id is None else host_id
    configs = local_backend_configs() if configs is None else configs
    started = time.monotonic()
    deadline = started + 10
    result = {"schema": "bach.local-model-catalog.v1", "host_id": host,
              "source": "configured_native_provider_metadata",
              "observed_at": datetime.now(timezone.utc).isoformat(),
              "runtime_verified": False, "models": [], "excluded": [], "providers": []}
    with httpx.Client(trust_env=False, follow_redirects=False) as client:
        for provider in ("ollama", "lmstudio"):
            config = configs.get(provider)
            if not config:
                continue
            status = {"backend": provider, "status": "unknown", "reason": "metadata_unavailable"}
            result["providers"].append(status)
            parsed = urlsplit(str(config.get("base_url", "")))
            if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                    or parsed.username or parsed.password or parsed.query or parsed.fragment):
                status["reason"] = "provider_not_local"
                continue
            base = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
            def read(method, endpoint, *, _base=base, **kwargs):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError("Metadatenbudget ausgeschöpft")
                return _json(client, method, _base + endpoint, timeout=min(3, remaining), deadline=deadline, **kwargs)
            try:
                if provider != "ollama":
                    # Keep unimplemented capability mapping explicit. The native
                    # dispatch verifier already handles LM Studio independently.
                    status["reason"] = "capability_adapter_pending"
                    continue
                payload = read("GET", "/api/tags")
                if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
                    raise TypeError("Ungültiger Modellkatalog")
                models = payload["models"]
                status.update(status="verified", reason=None)
                status["partial"] = len(models) > _MAX_MODELS
                seen = set()
                for entry in models[:_MAX_MODELS]:
                    name = entry.get("name") if isinstance(entry, dict) else None
                    try:
                        socket_id(provider, name, host)
                    except ValueError:
                        result["excluded"].append({"backend": provider, "model": name if isinstance(name, str) and len(name) <= 192 else None,
                                                   "reason": "cloud_or_invalid_target"})
                        continue
                    if name in seen:
                        continue
                    seen.add(name)
                    try:
                        metadata = read("POST", "/api/show", json={"model": name})
                        result["models"].append(_item(provider, name, host, metadata, entry.get("size")))
                    except (httpx.HTTPError, ValueError, TypeError):
                        status["partial"] = True
                        result["excluded"].append({"backend": provider, "model": name, "reason": "local_metadata_unverified"})
            except (httpx.HTTPError, ValueError, TypeError):
                status.update(status="unknown", reason="metadata_unavailable")
    return result
