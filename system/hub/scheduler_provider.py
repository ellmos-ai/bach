"""Provider seam for the scheduler extraction.

BACH keeps its legacy scheduler until parity is proven. New deployments can
install ``ellmos-scheduler`` and opt into the independent module through this
single import boundary instead of adding more scheduler logic to BACH.
"""
from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from typing import Any


EXTERNAL_MODULE = "ellmos_scheduler"


@dataclass(frozen=True)
class SchedulerProvider:
    name: str
    external: bool
    module: str | None
    reason: str


def probe_scheduler_provider() -> SchedulerProvider:
    """Describe the available provider without importing or starting it."""
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
