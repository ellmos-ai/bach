"""BACH-Adapter für ocean-resources (`ocean_resources.ram_distributor`, #2441, #2419).

Primärer Pfad lädt `RAMDistributor`, `WatchdogHysteresisPolicy`, `ConsumerCapability`,
`DistributorRequest` und `UserProximity` aus `ocean_resources.ram_distributor`.
Der ältere lokale Prototyp `OceanRamDistributor` aus `.MODULES/.CONTROL/ocean-resources/`
bleibt nur als `@deprecated_legacy_bach`-Fallback erhalten.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

from hub._services.ocean_stack_bridge import (
    deprecated_legacy_bach,
    get_ocean_ram_distributor,
    load_ocean_ram_distributor_module,
)

_MOD_PATH = Path(__file__).resolve().parents[3] / ".MODULES/.CONTROL/ocean-resources/ram_distributor.py"
_spec = importlib.util.spec_from_file_location("ocean_control_ocean_resources", _MOD_PATH)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

OceanRamDistributor = deprecated_legacy_bach("ocean_resources.ram_distributor.RAMDistributor")(
    _mod.OceanRamDistributor
)
PRIORITY_RANK = _mod.PRIORITY_RANK

_canonical_mod = load_ocean_ram_distributor_module()
RAMDistributor = _canonical_mod.RAMDistributor
WatchdogHysteresisPolicy = _canonical_mod.WatchdogHysteresisPolicy
ConsumerCapability = _canonical_mod.ConsumerCapability
DistributorRequest = _canonical_mod.DistributorRequest
UserProximity = _canonical_mod.UserProximity
FallbackDecision = _canonical_mod.FallbackDecision


def evaluate_ocean_ram_admission(
    *,
    available_ram_bytes: int,
    pressure: str = "normal",
    consumer_id: str,
    weights_ram_bytes: int,
    kv_reserve_bytes: int = 2 * 1024**3,
    overhead_bytes: int = 1 * 1024**3,
    seconds_since_model_load: float = 0.0,
    sustained_critical_seconds: float = 0.0,
) -> dict[str, Any]:
    """Evaluate model RAM admission and watchdog hysteresis via canonical ocean-resources."""
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "-", consumer_id.strip())
    dist = get_ocean_ram_distributor()
    dist.register_consumer(
        ConsumerCapability(
            consumer_id=safe_id,
            kind="model",
            weights_ram_bytes=weights_ram_bytes,
            kv_reserve_bytes=kv_reserve_bytes,
            overhead_bytes=overhead_bytes,
        )
    )
    decisions = dist.evaluate(
        [DistributorRequest(request_id=f"req-{safe_id}", consumer_id=safe_id)],
        available_ram_bytes=available_ram_bytes,
        pressure=pressure,
    )
    evict, evict_reason = dist.watchdog_policy.should_evict_model(
        available_ram_bytes=available_ram_bytes,
        pressure=pressure,
        seconds_since_model_load=seconds_since_model_load,
        sustained_critical_seconds=sustained_critical_seconds,
    )
    return {
        "schema": "bach.ocean-ram-admission.v1",
        "admission": decisions[0].as_dict() if decisions else {"admitted": False},
        "watchdog": {"evict": evict, "reason": evict_reason},
    }
