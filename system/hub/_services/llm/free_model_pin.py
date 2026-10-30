"""Per-run pinning of a tool-capable free OpenRouter model.

``openrouter_catalog`` answers which free model IDs are *currently* admissible
(proof from the provider model list, TTL cache, stale fallback).  This module
turns that list into a stable decision per worker run:

* one run id maps deterministically onto exactly one tool-capable free model,
  so a single run never switches models between its tool calls, and
* consecutive runs rotate because the mapping is a salted hash over the sorted
  candidate pool (not a counter, so no shared mutable state is required), and
* ``openrouter/free`` (the provider-side router) is the fallback whenever the
  catalog cannot supply a proven free model.

The module is deliberately free of I/O and of any worker/process coupling: it
only reads a catalog snapshot (or fetches the cached one) and returns a decision
dict.  Consumers keep their own transport; nothing here selects a backend.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from hub._services.llm.openrouter_catalog import (
    FREE_ROUTER_ID,
    get_openrouter_catalog,
)

_ROTATION_SALT = "bach-free-model-pin-v1"

FALLBACK_REASONS = (
    "run_id_missing",
    "catalog_stale",
    "no_free_candidates",
)


def _normalize_run_id(run_id: Any) -> str:
    if run_id is None:
        return ""
    return str(run_id).strip()


def _is_tool_capable_candidate(record: Any) -> bool:
    """An admitted catalog record counts as tool-capable by construction.

    ``openrouter_catalog`` denies admission to models that publish a parameter
    list without ``tools`` and to everything that is not a ``:free`` variant.
    The provider router is always admitted, so it is excluded here explicitly:
    it is the fallback, not a rotation member.
    """
    if not isinstance(record, Mapping):
        return False
    if record.get("free") is not True:
        return False
    if record.get("kind") == "provider_router":
        return False
    model_id = record.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return False
    return model_id.strip() != FREE_ROUTER_ID


def _is_plain_candidate(record: Any) -> bool:
    if not isinstance(record, Mapping):
        return False
    model_id = record.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return False
    return model_id.strip() != FREE_ROUTER_ID


def free_candidates(
    catalog: Mapping[str, Any] | None,
    *,
    tool_capable_only: bool = True,
) -> list[str]:
    """Return the sorted rotation pool of free model ids.

    Sorting is case-folded with the raw id as tie breaker, so the pool does not
    depend on provider response order (an empty pool means "use the router").
    """
    if not isinstance(catalog, Mapping):
        return []
    models = catalog.get("models")
    if not isinstance(models, list):
        return []
    check = _is_tool_capable_candidate if tool_capable_only else _is_plain_candidate
    ids: set[str] = set()
    for record in models:
        if not check(record):
            continue
        model_id = record.get("id")
        if isinstance(model_id, str):
            ids.add(model_id.strip())
    return sorted(ids, key=lambda item: (item.casefold(), item))


def rotation_index(run_id: str, size: int) -> int:
    """Deterministic bucket for ``run_id`` inside a pool of ``size`` models."""
    if size <= 0:
        raise ValueError("rotation pool must not be empty")
    digest = hashlib.sha256(f"{_ROTATION_SALT}:{run_id}".encode("utf-8")).hexdigest()
    return int(digest, 16) % size


def _fallback(
    run_id: str,
    catalog: Mapping[str, Any] | None,
    reason: str,
    *,
    tool_capable_only: bool,
) -> dict[str, Any]:
    snapshot = catalog if isinstance(catalog, Mapping) else {}
    return {
        "model": FREE_ROUTER_ID,
        "run_id": run_id,
        "fallback": True,
        "pinned": False,
        "reason": reason,
        "candidates": [],
        "rotation_index": None,
        "source": snapshot.get("source"),
        "stale": bool(snapshot.get("stale")),
        "tool_capable_only": tool_capable_only,
    }


def pick_free_model(
    run_id: Any,
    *,
    catalog: Mapping[str, Any] | None = None,
    tool_capable_only: bool = True,
    success_rates: Any = None,
) -> dict[str, Any]:
    """Pin one tool-capable free model for ``run_id``.

    ``catalog`` may be an already fetched ``get_openrouter_catalog()`` result;
    otherwise the cached catalog is read (no forced refresh, no network call on
    a warm cache).  The decision dict always carries ``model``; ``fallback``
    states whether the provider router was chosen and ``reason`` explains why.
    """
    run_key = _normalize_run_id(run_id)
    snapshot = catalog if catalog is not None else get_openrouter_catalog()
    if not isinstance(snapshot, Mapping):
        snapshot = {}

    if snapshot.get("stale"):
        return _fallback(
            run_key,
            snapshot,
            str(snapshot.get("failure_code") or "catalog_stale"),
            tool_capable_only=tool_capable_only,
        )

    candidates = free_candidates(snapshot, tool_capable_only=tool_capable_only)
    if not candidates:
        return _fallback(
            run_key, snapshot, "no_free_candidates", tool_capable_only=tool_capable_only
        )
    if not run_key:
        return _fallback(
            run_key, snapshot, "run_id_missing", tool_capable_only=tool_capable_only
        )

    index = rotation_index(run_key, len(candidates))
    if success_rates is not None:

        def _rate(model_id: str) -> float:
            if callable(success_rates):
                return float(success_rates(model_id))
            value = success_rates.get(model_id)
            return 0.0 if value is None else float(value)

        ordered = sorted(candidates, key=lambda item: (-_rate(item), int.from_bytes(hashlib.sha256(f"{_ROTATION_SALT}:{run_key}:{item}".encode("utf-8")).digest()[:8], "big")))
        return {
            "model": ordered[0],
            "run_id": run_key,
            "fallback": False,
            "pinned": True,
            "reason": None,
            "candidates": ordered,
            "rotation_index": index,
            "source": snapshot.get("source"),
            "stale": False,
            "tool_capable_only": tool_capable_only,
        }
    return {
        "model": candidates[index],
        "run_id": run_key,
        "fallback": False,
        "pinned": True,
        "reason": None,
        "candidates": candidates,
        "rotation_index": index,
        "source": snapshot.get("source"),
        "stale": False,
        "tool_capable_only": tool_capable_only,
    }


def pinned_model(run_id: Any, **kwargs: Any) -> str:
    """Convenience wrapper returning only the model id (pinned or router)."""
    return pick_free_model(run_id, **kwargs)["model"]


__all__ = [
    "FALLBACK_REASONS",
    "free_candidates",
    "pick_free_model",
    "pinned_model",
    "rotation_index",
]
