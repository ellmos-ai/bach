# SPDX-License-Identifier: MIT
"""PB-26 Paket 3: the RAM distributor's run cooldown for a local model worker.

The admission itself lives in ocean-resources (``RunCooldownGate``, ``sample_stress``);
BACH only opens a gate at the end of a run and asks it. Loaded lazily, so a host whose
ocean-resources predates PB-26 keeps the plain slot pause.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def is_local_model(backend, model) -> bool:
    """A local Ollama model holds host memory; ``…cloud`` models only pass through."""
    from hub._services.llm.model_backend import OllamaBackend

    return (isinstance(backend, OllamaBackend) and isinstance(model, str) and bool(model.strip())
            and not model.rsplit(":", 1)[-1].lower().endswith("cloud"))


def open_gate(backend, model):
    """``(gate, sampler)`` primed with the run-end sample, or None (no local model, no gate)."""
    if not is_local_model(backend, model):
        return None
    try:
        from hub._services.ocean_stack_bridge import load_ocean_ram_distributor_module

        mod = load_ocean_ram_distributor_module()
        gate_type, sampler = mod.RunCooldownGate, mod.sample_stress
    except Exception:  # noqa: BLE001 -- no gate is the pre-PB-26 behaviour, never a stop
        log.info("run_cooldown unavailable: ocean-resources without RunCooldownGate")
        return None
    try:
        baseline = sampler()
    except Exception:  # noqa: BLE001 -- an unmeasured run end still gets the minimum pause
        baseline = None
    return gate_type(baseline=baseline), sampler
