"""Provider seam for the scheduler extraction.

BACH keeps its legacy scheduler until parity is proven. New deployments can
install ``ellmos-scheduler`` and opt into the independent module through this
single import boundary instead of adding more scheduler logic to BACH.

Rollback rule (MODULRUECKTRANSFER-PLAN section 4, rule 1): setting the
environment variable ``BACH_USE_EXTERNAL_SCHEDULER=0`` forces BACH back onto
the internal legacy path immediately, even when the external module is
importable. No other switch is required to revert a deployment.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
from dataclasses import dataclass
from typing import Any


EXTERNAL_MODULE = "ellmos_scheduler"
ROLLBACK_ENV_VAR = "BACH_USE_EXTERNAL_SCHEDULER"
ADAPTER_FACTORY = "create_bach_adapter"
_ROLLBACK_OFF_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class SchedulerProvider:
    name: str
    external: bool
    module: str | None
    reason: str


def _rollback_forced() -> bool:
    return os.environ.get(ROLLBACK_ENV_VAR, "").strip().lower() in _ROLLBACK_OFF_VALUES


def probe_scheduler_provider() -> SchedulerProvider:
    """Describe the available provider without importing or starting it."""
    if _rollback_forced():
        return SchedulerProvider(
            name="bach-legacy",
            external=False,
            module=None,
            reason=f"rollback switch {ROLLBACK_ENV_VAR}=0 forces the internal scheduler",
        )
    if importlib.util.find_spec(EXTERNAL_MODULE) is not None:
        return SchedulerProvider(
            name="ellmos-scheduler",
            external=True,
            module=EXTERNAL_MODULE,
            reason="independent module is importable",
        )
    return SchedulerProvider(
        name="bach-legacy",
        external=False,
        module=None,
        reason="ellmos-scheduler is not installed in this environment",
    )


def load_external_scheduler() -> Any:
    """Import the independent scheduler explicitly.

    No silent fallback is used here: callers that choose the external provider
    must receive a clear import error if deployment wiring is incomplete.
    """
    return importlib.import_module(EXTERNAL_MODULE)


def create_external_scheduler_adapter(state_db: Any) -> Any:
    """Build a ``BachSchedulerAdapter`` for the external scheduler store.

    This is the only sanctioned way for BACH handlers to obtain the external
    adapter. It fails closed with a clear contract error if the installed
    module does not export ``create_bach_adapter`` (wiring contract of
    ellmos-scheduler >= 0.3).
    """
    module = load_external_scheduler()
    factory = getattr(module, ADAPTER_FACTORY, None)
    if factory is None:
        raise AttributeError(
            f"{EXTERNAL_MODULE} does not export {ADAPTER_FACTORY}(); "
            "ellmos-scheduler >= 0.3 with the BACH adapter contract is required"
        )
    return factory(state_db)