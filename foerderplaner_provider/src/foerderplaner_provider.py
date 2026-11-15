"""Provider seam for the foerderplaner extraction.

BACH keeps its legacy foerderplaner until parity is proven. New deployments can
install ``foerderplaner`` and opt into the independent module through this
single import boundary instead of adding more logic to BACH.

Rollback rule (MODULRUECKTRANSFER-PLAN section 4, rule 1): setting the
environment variable ``BACH_USE_EXTERNAL_FOERDERPLANER=0`` forces BACH back onto
the internal legacy path immediately, even when the external module is importable. No other switch is required to revert a deployment.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
from dataclasses import dataclass
from typing import Any

EXTERNAL_MODULE = "foerderplaner"
ROLLBACK_ENV_VAR = "BACH_USE_EXTERNAL_FOERDERPLANER"
ADAPTER_FACTORY = "create_foerderplaner_adapter"
_ROLLBACK_OFF_VALUES = {"0", "false", "no", "off"}
@dataclass(frozen=True)
class FoerderplanerProvider:
    name: str
    external: bool
    module: str | None
    reason: str
def _rollback_forced() -> bool:
    return os.environ.get(ROLLBACK_ENV_VAR, "").strip().lower() in _ROLLBACK_OFF_VALUES
def probe_foerderplaner_provider() -> FoerderplanerProvider:
    """Describe the available provider without importing or starting it."""
    if _rollback_forced():
        return FoerderplanerProvider(
            name="foerderplaner-legacy",
            external=False,
            module=None,
            reason=f"rollback switch {ROLLBACK_ENV_VAR}=0 forces the internal foerderplaner",
        )
    if importlib.util.find_spec(EXTERNAL_MODULE) is not None:
        return FoerderplanerProvider(
            name="foerderplaner",
            external=True,
            module=EXTERNAL_MODULE,
            reason="independent module is importable",
        )
    return FoerderplanerProvider(
        name="foerderplaner-legacy",
        external=False,
        module=None,
        reason="foerderplaner is not installed in this environment",
    )
def load_external_foerderplaner() -> Any:
    """Import the independent foerderplaner explicitly.

    No silent fallback is used here: callers that choose the external provider
    must receive a clear import error if deployment wiring is incomplete.
    """
    return importlib.import_module(EXTERNAL_MODULE)
def create_external_foerderplaner_adapter(state_db: Any, **options: Any) -> Any:
    """Build a ``FoerderplanerAdapter`` for the external foerderplaner store.

    This is the only sanctioned way for BACH handlers to obtain the external
    adapter. It fails closed with a clear contract error if the installed
    module does not export ``create_foerderplaner_adapter`` (wiring contract of
    foerderplaner >= 0.3).
    """
    module = load_external_foerderplaner()
    factory = getattr(module, ADAPTER_FACTORY, None)
    if factory is None:
        raise AttributeError(
            f"{EXTERNAL_MODULE} does not export {ADAPTER_FACTORY}(); "
            "foerderplaner >= 0.3 with the BACH adapter contract is required"
        )
    return factory(state_db, **options)
def create_documentation_foerderplaner(
    state_db: Any, executor: Any, *, worker_id: str
) -> Any:
    """Compose a BACH executor with the existing module's scheduling authority."""
    if not probe_foerderplaner_provider().external:
        raise RuntimeError("External foerderplaner unavailable or rollback requested")
    module = load_external_foerderplaner()
    registry = module.ExecutorRegistry(include_standard=False)

    def execute(payload, timeout_seconds):
        try:
            value = executor(payload, timeout_seconds)
            import json

            return module.ExecutionResult(
                "succeeded", exit_code=0, output=json.dumps(value, ensure_ascii=False)
            )
        except Exception:  # noqa: BLE001 - native errors may contain private configuration
            # Native API responses/configuration can contain private details.
            return module.ExecutionResult(
                "failed", error="foerderplaner_dispatch_failed"
            )

    registry.register("bach-docs", execute)
    return create_external_foerderplaner_adapter(
        state_db, registry=registry, worker_id=worker_id
    )