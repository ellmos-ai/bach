# SPDX-License-Identifier: MIT
"""Limits and cleanup for Buddha's explicitly configured, monitored cold start.

This is a supervised load admission, not a memory certification: the static
reserve arithmetic stays the default. Observations (pressure, swap, available
memory) only ever abort a load; they never create capacity.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

STALE_SECONDS = 5.0


def limits_violation(gate, sample, *, elapsed, sample_age, hard_floor_bytes):
    """Name of the first violated limit, or None. Missing data fails closed."""
    if elapsed > gate["max_load_seconds"]:
        return "load_time_exceeded"
    if not isinstance(sample, dict) or sample_age > STALE_SECONDS:
        return "observation_stale"
    available = sample.get("memory_available_bytes")
    pressure = sample.get("pressure_level")
    swap_used = sample.get("swap_used_bytes")
    if type(available) is not int or available < hard_floor_bytes:
        return "memory_floor_breached"
    if type(pressure) is not int or pressure > gate["max_pressure_level"]:
        return "pressure_exceeded"
    if (type(swap_used) is not int
            or swap_used - gate["baseline"]["swap_used_bytes"] > gate["max_swap_growth_bytes"]):
        return "swap_growth_exceeded"
    return None


async def sample_host():
    import psutil
    from hub._services.chat.host_resource_observation import observe_host_resources

    return await asyncio.to_thread(lambda: observe_host_resources(psutil.virtual_memory()))


def _track(stats, sample):
    """Keep only measured extremes; nothing here is ever credited as capacity."""
    if stats is None or not isinstance(sample, dict):
        return
    stats["samples"] = stats.get("samples", 0) + 1
    for key, pick in (("memory_available_bytes", min), ("swap_used_bytes", max),
                      ("pressure_level", max), ("compressor_physical_bytes", max)):
        value = sample.get(key)
        if type(value) is int:
            stats[key] = pick(stats[key], value) if key in stats else value


def _observation_path():
    from hub._services.chat.local_resource_reserve import runtime_root

    return runtime_root() / "local-inference/load-observations.json"


def read_observation(model, digest):
    """Last measured load of exactly this model digest; observed values only."""
    try:
        record = json.loads(_observation_path().read_bytes()).get(model)
    except (OSError, ValueError, AttributeError):
        return None
    return record if isinstance(record, dict) and record.get("digest") == digest else None


async def resident_footprint(base_url, model, digest):
    """Measured residency (size, VRAM, context) of the exact loaded model, or None."""
    parsed = urlsplit(str(base_url))
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        return None
    names = {model} if ":" in model.rsplit("/", 1)[-1] else {model, model + ":latest"}
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
            listed = (await client.get(str(base_url).rstrip("/") + "/api/ps")).json().get("models")
    except (OSError, ValueError, httpx.HTTPError):
        return None
    for item in listed if isinstance(listed, list) else []:
        if (isinstance(item, dict) and item.get("digest") == digest
                and (item.get("name") in names or item.get("model") in names)):
            return {key: item.get(key) for key in ("size", "size_vram", "context_length")}
    return None


def record_observation(model, digest, num_ctx, stats, baseline, footprint):
    """Persist one measured cold load next to, never inside, the policy budgets."""
    path = _observation_path()
    try:
        data = json.loads(path.read_bytes())
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    record = {"schema": "bach.local-load-observation.v1", "digest": digest, "num_ctx": num_ctx,
              "measured_at": datetime.now(timezone.utc).isoformat(), "credited_as_capacity": False,
              "baseline": baseline, "extremes": stats, "resident": footprint}
    data[model] = record
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(json.dumps(data, indent=1, sort_keys=True).encode("utf-8"))
    os.replace(tmp, path)
    return record


async def monitor_load(load, gate, *, hard_floor_bytes, check, interval=1.0, stats=None):
    """Await ``load`` while enforcing the cold-start limits.

    Returns (result, None) on completion or (None, reason) after cancelling the
    load. ``check`` is the caller's binding/stop check and may return a reason.
    """
    started = time.monotonic()
    sample, sampled_at = gate["baseline"], started
    _track(stats, sample)
    pending = None
    while not load.done():
        await asyncio.wait({load}, timeout=0.1)
        reason = check()
        if reason is None and pending is not None and pending.done():
            try:
                sample, sampled_at = pending.result(), time.monotonic()
                _track(stats, sample)
            except Exception:
                pass
            pending = None
        if reason is None and pending is None and time.monotonic() - sampled_at >= interval:
            pending = asyncio.create_task(sample_host())
        if reason is None:
            reason = limits_violation(
                gate, sample, elapsed=time.monotonic() - started,
                sample_age=time.monotonic() - sampled_at, hard_floor_bytes=hard_floor_bytes)
        if reason:
            load.cancel()
            for task in (load, pending):
                if task is None:
                    continue
                task.cancel()
                try:
                    await task
                except BaseException:
                    pass
            return None, reason
    if pending is not None:
        pending.cancel()
    if stats is not None:
        stats["elapsed_seconds"] = round(time.monotonic() - started, 2)
    return load.result(), None


async def unload_exact_model(base_url, model, digest, *, wait_seconds=10.0):
    """Unload ``model`` (keep_alive=0); True only once /api/ps no longer lists it."""
    parsed = urlsplit(str(base_url))
    if (parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            or parsed.username or parsed.password):
        return False
    base = str(base_url).rstrip("/")
    names = {model} if ":" in model.rsplit("/", 1)[-1] else {model, model + ":latest"}
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
            await client.post(base + "/api/generate", json={"model": model, "keep_alive": 0})
            deadline = time.monotonic() + wait_seconds
            while True:
                listed = (await client.get(base + "/api/ps")).json().get("models")
                if not isinstance(listed, list):
                    return False
                if not any(isinstance(m, dict) and m.get("digest") == digest
                           and (m.get("name") in names or m.get("model") in names)
                           for m in listed):
                    return True
                if time.monotonic() >= deadline:
                    return False
                await asyncio.sleep(0.5)
    except (OSError, ValueError, httpx.HTTPError):
        return False
