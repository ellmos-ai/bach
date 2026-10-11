# SPDX-License-Identifier: MIT
"""Optional host reserve barrier at the existing model-call boundary.

No model load/unload, task claims, replay, filesystem cleanup or scheduler lives
here. The policy is a capacity constraint, not another model router. Missing
policy preserves legacy operation; an existing invalid policy fails closed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psutil

SCHEMA = "bach.local-resource-reserve.v1"
GIB = 1024**3
_MAX_POLICY = 32_768
_MAX_RESPONSE = 262_144
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,191}\Z")


class LocalReserveError(RuntimeError):
    """Public enum only: no URL, provider body, path or prompt escapes."""


def runtime_root() -> Path:
    return Path(os.environ.get("BACH_RUNTIME_DIR") or Path.home() / ".bach/runtime").expanduser().resolve()


def policy_path() -> Path:
    return runtime_root() / "local-inference/resource-reserve.json"


def _integer(raw, low, high):
    if type(raw) is not int or not low <= raw <= high:
        raise ValueError("invalid capacity integer")
    return raw


def validate_policy(raw):
    fields = {"schema", "enabled", "memory_reserve_bytes", "disk_reserve_bytes",
              "wait_seconds", "poll_seconds", "models"}
    if (not isinstance(raw, dict) or set(raw) != fields or raw["schema"] != SCHEMA
            or type(raw["enabled"]) is not bool):
        raise ValueError("invalid reserve policy")
    _integer(raw["memory_reserve_bytes"], 512 * 1024**2, 64 * GIB)
    _integer(raw["disk_reserve_bytes"], 128 * 1024**2, 256 * GIB)
    _integer(raw["wait_seconds"], 1, 3600)
    _integer(raw["poll_seconds"], 1, 60)
    models = raw["models"]
    if not isinstance(models, dict) or len(models) > 32:
        raise ValueError("invalid model budgets")
    for name, budget in models.items():
        if (not isinstance(name, str) or not _MODEL.fullmatch(name)
                or name.lower().endswith(":cloud") or not isinstance(budget, dict)
                or set(budget) != {"digest", "weight_budget_bytes", "kv_headroom_bytes",
                                   "overhead_bytes", "num_ctx"}
                or not isinstance(budget["digest"], str) or not _DIGEST.fullmatch(budget["digest"])):
            raise ValueError("invalid model budget")
        _integer(budget["weight_budget_bytes"], 1, 1024 * GIB)
        _integer(budget["kv_headroom_bytes"], 128 * 1024**2, 256 * GIB)
        _integer(budget["overhead_bytes"], 128 * 1024**2, 64 * GIB)
        _integer(budget["num_ctx"], 512, 262_144)
    return raw


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate policy field")
        result[key] = value
    return result


def read_policy():
    path = policy_path()
    if any(part.lower().startswith("onedrive") for part in path.parts):
        raise ValueError("cloud-synced runtime")
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("symlink policy")
    try:
        with path.open("rb") as handle:
            data = handle.read(_MAX_POLICY + 1)
    except FileNotFoundError:
        return None, None
    if len(data) > _MAX_POLICY:
        raise ValueError("oversized reserve policy")
    return validate_policy(json.loads(data, object_pairs_hook=_unique_object)), hashlib.sha256(data).hexdigest()


def _data_roots():
    # Path resolution does not open or migrate the canonical task database.
    from hub._services.chat.slots_config import DEFAULT_SLOTS_FILE

    from bach_api import _resolve_db_path
    roots = {"taskdb": _resolve_db_path().parent, "runtime": runtime_root(),
             "slots": Path(DEFAULT_SLOTS_FILE).expanduser().parent}
    result = {}
    for label, root in roots.items():
        while not root.exists() and root != root.parent:
            root = root.parent
        result[label] = root
    return result


async def _native_json(client, method, url, *, payload=None):
    async with client.stream(method, url, json=payload) as response:
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes(chunk_size=8192):
            if len(data) + len(chunk) > _MAX_RESPONSE:
                raise ValueError("oversized model observation")
            data.extend(chunk)
    result = json.loads(data)
    if not isinstance(result, dict):
        raise TypeError("invalid model observation")
    return result


def _models(payload):
    items = payload.get("models")
    if (not isinstance(items, list) or len(items) > 256
            or any(not isinstance(item, dict) for item in items)):
        raise ValueError("invalid model collection")
    return items


def _remote_evidence(record):
    fields = [record.get("remote_host"), record.get("remote_model")]
    if any(value is not None and not isinstance(value, str) for value in fields):
        raise TypeError("invalid remote evidence")
    if any(isinstance(value, str) and len(value) > 2048 for value in fields):
        raise ValueError("oversized remote evidence")
    return any(isinstance(value, str) and value.strip() for value in fields)


def _catalog_identity(record):
    fields = [record[key] for key in ("name", "model") if key in record]
    if not fields or any(not isinstance(value, str) or not _MODEL.fullmatch(value) for value in fields):
        raise ValueError("invalid catalog identity")
    names = {value if ":" in value.rsplit("/", 1)[-1] else value + ":latest" for value in fields}
    if len(names) != 1:
        raise ValueError("conflicting catalog identity")
    return names.pop()


async def observe_ollama(backend, name):
    """Read-only native metadata; exact tags/digests, no prefix equivalence."""
    base = str(getattr(backend, "base_url", ""))
    parsed = urlsplit(base)
    if (parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("unverified local endpoint")
    async with httpx.AsyncClient(timeout=2, follow_redirects=False, trust_env=False) as client:
        async with asyncio.timeout(4):
            shown = await _native_json(client, "POST", base.rstrip("/") + "/api/show", payload={"model": name})
            if _remote_evidence(shown):
                return {"external": True}
            # Native cloud /show may omit remote fields and its local format.
            # Only the exact, unique catalog identity can supply that evidence.
            tags = _models(await _native_json(client, "GET", base.rstrip("/") + "/api/tags"))
            names = {name} if ":" in name.rsplit("/", 1)[-1] else {name, name + ":latest"}
            matches = [item for item in tags if _catalog_identity(item) in names]
            if len(matches) != 1:
                raise ValueError("ambiguous catalog identity")
            item = matches[0]
            if _remote_evidence(item):
                return {"external": True}
            details, info = shown.get("details"), shown.get("model_info")
            if (not isinstance(details, dict) or details.get("format") not in {"gguf", "safetensors", "mlx"}
                    or not isinstance(info, dict)
                    or type(info.get("general.parameter_count")) is not int
                    or info["general.parameter_count"] <= 0):
                raise ValueError("unverified local metadata")
            loaded = _models(await _native_json(client, "GET", base.rstrip("/") + "/api/ps"))
    digest, weight_floor = item.get("digest"), item.get("size")
    if (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
            or type(weight_floor) is not int or weight_floor <= 0):
        raise ValueError("invalid catalog identity")
    resident = [item for item in loaded if item.get("digest") == digest
                and (item.get("name") in names or item.get("model") in names)]
    if len(resident) > 1:
        raise ValueError("ambiguous residency")
    context = resident[0].get("context_length") if resident else None
    return {"external": False, "digest": digest, "weight_floor_bytes": weight_floor,
            "resident_context": context if type(context) is int and context > 0 else None}


def _decision(state, *, admitted=False, enforced=True, retryable=False, **fields):
    return {"schema": SCHEMA, "state": state, "admitted": admitted, "enforced": enforced,
            "retryable": retryable, "checked_at": datetime.now(timezone.utc).isoformat(), **fields}


async def probe(backend, model):
    """A budget/observation receipt, never a model capacity certification."""
    try:
        policy, version = read_policy()
    except (OSError, ValueError, TypeError, UnicodeError):
        return _decision("invalid_policy")
    if policy is None:
        return _decision("not_configured", admitted=True, enforced=False)
    if not policy["enabled"]:
        return _decision("disabled", admitted=True, enforced=False, policy_version=version)
    if not isinstance(model, str) or not _MODEL.fullmatch(model):
        return _decision("unknown_model")
    from hub._services.llm.model_backend import backend_identifier
    if backend_identifier(backend) != "ollama":
        return _decision("unsupported_provider")
    common = {"policy_version": version, "model": model,
              "wait_seconds": policy["wait_seconds"], "poll_seconds": policy["poll_seconds"]}
    try:
        observed = await observe_ollama(backend, model)
    except (OSError, ValueError, TypeError, httpx.HTTPError, TimeoutError):
        return _decision("unknown_model_observation", retryable=True, **common)
    if observed["external"]:
        return _decision("external_target", admitted=True, enforced=False, **common)
    budget = policy["models"].get(model)
    if budget is None:
        return _decision("missing_model_budget", **common)
    if (budget["digest"] != observed["digest"]
            or budget["weight_budget_bytes"] < observed["weight_floor_bytes"]
            or budget["num_ctx"] != getattr(backend, "num_ctx", None)):
        return _decision("model_budget_conflict", **common)
    try:
        memory = psutil.virtual_memory()
        total = _integer(memory.total, 1, 4096 * GIB)
        available = _integer(memory.available, 0, total)
        free = {label: _integer(shutil.disk_usage(path).free, 0, 1024 * 1024 * GIB)
                for label, path in _data_roots().items()}
    except (OSError, ValueError, TypeError, AttributeError):
        return _decision("unknown_resources", retryable=True, **common)
    # A matching resident model with a sufficient observed context avoids a
    # second weight reservation. KV/overhead headroom remains conservative;
    # it is configured budget, not invented measured memory consumption.
    resident = (observed["resident_context"] is not None
                and observed["resident_context"] >= budget["num_ctx"])
    weight_request = 0 if resident else budget["weight_budget_bytes"]
    required = (policy["memory_reserve_bytes"] + weight_request
                + budget["kv_headroom_bytes"] + budget["overhead_bytes"])
    common.update({"memory_total_bytes": total, "memory_available_bytes": available,
                   "memory_required_bytes": required, "disk_free_bytes": free,
                   "disk_reserve_bytes": policy["disk_reserve_bytes"],
                   "weight_request_bytes": weight_request, "resident_weight_credit": resident})
    if required > total:
        return _decision("budget_exceeds_host", **common)
    if any(value < policy["disk_reserve_bytes"] for value in free.values()):
        return _decision("waiting_disk_reserve", retryable=True, **common)
    if available < required:
        return _decision("waiting_memory_reserve", retryable=True, **common)
    return _decision("ready", admitted=True, **common)


def require_retryable(receipt):
    if not receipt["admitted"] and not receipt["retryable"]:
        raise LocalReserveError("Lokale Ressourcenfreigabe: " + receipt["state"])
