# BACH Adapter: resource_load_pending
# SPDX-License-Identifier: MIT
"""Native readbacks for Ocean's staged model-load contract.

Ollama 0.33.3 does not expose a reviewed mapping from its Metal allocation to
private, non-reclaimable host pages. RSS/USS/phys_footprint and API ``size_vram``
are not interchangeable with the available-RAM sensor. Consequently this port
does not yet advertise LOAD_PENDING admission. The protocol remains opt-in and
unavailable on this provider until an independently reviewed accounting source
can implement that mapping; no operator JSON boolean can supply the evidence.
"""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from hub._services.chat.host_inference_gate import HostInferenceGate
from hub._services.ocean_resources_provider import load_verified

REVIEWED_POLICY_SHA256 = "e638d2f4a4423fb543b3dece6e46f6b8689c21ef6e15d6e1c25ccb164a1eae9b"
GIB = 1024**3


def native_resident_credit(*, api_size, process_rss):
    # A large API allocation or RSS is not a proved, model-specific lower bound
    # excluded from available RAM. In particular footprint includes compressed
    # and swapped pages. Missing evidence is zero credit, never an estimate.
    return None


def verified_wired_resident_credit(
    *,
    scope,
    before_sample_epoch,
    after_sample_epoch,
    pre_commit_epoch,
    platform_sample,
    observed_at,
):
    """Build a verified ResidentCredit v2 via the pinned ocean-resources package.

    Stock Ollama 0.33.3 does not supply a cooperative WiredEpoch or signed
    /usr/bin/vm_stat bracket and continues to use ``native_resident_credit``
    (zero credit, ``supports_load_pending = False``). Any missing or mismatched
    binding fails closed inside ``ocean_resources.model_loading``.
    """
    native = load_verified(("ocean_resources.model_loading",))["ocean_resources.model_loading"]
    return native.build_wired_resident_credit(
        scope=scope,
        before_sample_epoch=before_sample_epoch,
        after_sample_epoch=after_sample_epoch,
        pre_commit_epoch=pre_commit_epoch,
        platform_sample=platform_sample,
        observed_at=observed_at,
    )


def native_model_process(spec):
    """Read the single exact loopback listener and its stable owned process tree.

    RSS is a diagnostic upper-bound check, not credited RAM. No process command
    line, environment, user data, signal or model request is read or emitted.
    """
    import psutil
    if platform.system() != "Darwin":
        raise RuntimeError("native_model_process_scope_unreviewed")
    result = subprocess.run(["/usr/sbin/lsof", "-nP", f"-iTCP:{spec.port}", "-sTCP:LISTEN", "-Fpcn"],
        capture_output=True, text=True, timeout=3, check=True)
    if len(result.stdout) > 65536:
        raise RuntimeError("native_model_listener_ambiguous")
    pids = {int(line[1:]) for line in result.stdout.splitlines() if line.startswith("p") and line[1:].isdigit()}
    endpoints = {line[1:] for line in result.stdout.splitlines() if line.startswith("n")}
    if len(pids) != 1 or endpoints != {f"127.0.0.1:{spec.port}"}:
        raise RuntimeError("native_model_listener_ambiguous")
    root = psutil.Process(pids.pop())
    boot = psutil.boot_time()
    def sample():
        processes = [root, *root.children(recursive=True)]
        if len(processes) > 128:
            raise RuntimeError("native_model_process_scope_exceeded")
        identities, rss = [], 0
        for process in processes:
            if (not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
                    or Path(process.exe()).name != "ollama"):
                raise RuntimeError("native_model_process_scope_changed")
            identities.append((process.pid, process.create_time()))
            value = process.memory_info().rss
            if type(value) is not int or value <= 0:
                raise RuntimeError("native_model_rss_unavailable")
            rss += value
        return tuple(sorted(identities)), rss
    before, rss1 = sample()
    after, rss2 = sample()
    if before != after or not root.is_running() or root.create_time() != dict(before)[root.pid]:
        raise RuntimeError("native_model_process_identity_changed")
    return {"pid": root.pid, "created_at": root.create_time(), "boot_time": boot}, max(rss1, rss2)


def observe_under_owner(port, spec, policy_sha256, *, loaded, expected_process, capacity_reader, deadline):
    """Independent observations while the existing inference owner excludes POSTs."""
    import shutil

    import psutil
    from hub._services.chat.host_resource_observation import observe_host_resources
    from hub._services.chat.local_resource_reserve import (
        _cold_start_gate,
        _data_roots,
        read_policy,
    )

    native = load_verified(("ocean_resources.model_loading",))["ocean_resources.model_loading"]
    gate = HostInferenceGate.current_owner()
    held = gate._check_owned_record()
    if "dispatch_pending" in held.record:
        raise RuntimeError("model_dispatch_still_unconfirmed")
    started = port.clock()
    policy, version = read_policy()
    if (policy_sha256 != REVIEWED_POLICY_SHA256 or version != policy_sha256
            or not policy or policy["enabled"] is not True):
        raise RuntimeError("reviewed_cold_start_policy_changed")
    cold = policy.get("cold_start")
    if (cold != {"enabled": True, "min_available_bytes": 6 * GIB, "max_load_seconds": 300,
                 "max_pressure_level": 2, "max_swap_growth_bytes": 8 * GIB}
            or policy["memory_reserve_bytes"] != 2 * GIB):
        raise RuntimeError("reviewed_cold_start_limits_changed")
    budget = policy["models"].get(spec.model)
    if not budget or budget["digest"] != spec.digest or budget["num_ctx"] != spec.context_tokens:
        raise RuntimeError("reviewed_model_policy_binding_changed")
    process, rss = native_model_process(spec)
    if expected_process is not None and process != expected_process:
        raise RuntimeError("model_process_identity_changed")
    port._available(spec, deadline)
    first = port._api(spec, "/api/ps", deadline)
    target = port._target(spec, first, residency=True)
    if len(first["models"]) != (1 if loaded else 0) or bool(target) is not loaded:
        raise RuntimeError("another_or_missing_model_is_resident")
    if loaded and target.get("context_length") != spec.context_tokens:
        raise RuntimeError("resident_model_context_changed")
    memory = psutil.virtual_memory()
    sample = observe_host_resources(memory)
    available = memory.available
    if (type(available) is not int or available < 2 * GIB
            or type(sample.get("pressure_level")) is not int or sample["pressure_level"] not in {1, 2}
            or type(sample.get("swap_used_bytes")) is not int or sample["swap_used_bytes"] < 0
            or any(shutil.disk_usage(path).free < policy["disk_reserve_bytes"] for path in _data_roots().values())):
        raise RuntimeError("original_resource_observation_unavailable")
    if not loaded and _cold_start_gate(policy, True, False, sample, available, spec.digest) is None:
        raise RuntimeError("original_cold_start_gate_not_admitted")
    capacity = capacity_reader()
    last = port._api(spec, "/api/ps", deadline)
    process_after, rss_after = native_model_process(spec)
    if (first != last or process != process_after or read_policy()[1] != policy_sha256
            or port.clock() >= deadline):
        raise RuntimeError("native_load_observation_changed")
    gate._check_owned_record()
    return native.LoadObservation(spec.fingerprint(), policy_sha256, native.ProcessIdentity(**process),
        started, available, sample["pressure_level"], sample["swap_used_bytes"],
        target["size"] if target else 0, max(rss, rss_after), target.get("context_length") if target else None,
        budget["kv_headroom_bytes"] + budget["overhead_bytes"], capacity,
        native_resident_credit(api_size=target["size"] if target else 0, process_rss=max(rss, rss_after)))
