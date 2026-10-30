"""Thin BACH adapter for the provider-neutral agent-library module."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping

_MODULE_NAME = "bach_agent_library_core"
_MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / ".MODULES" / ".CONTROL" / "agent-library" / "agent_library.py"
)

_BACH_ERRORS = {
    "profile_identity_invalid": "worker_delete_execution_unconfirmed",
    "profile_identity_mismatch": "worker_delete_execution_unconfirmed",
    "execution_proof_required": "worker_delete_execution_unconfirmed",
    "deletion_port_unavailable": "worker_delete_execution_unconfirmed",
    "terminal_receipts_unconfirmed": "worker_delete_budget_unconfirmed",
}


def _load_agent_library():
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _MODULE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"agent-library-Modul nicht ladbar: {_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


_agent_library = _load_agent_library()


def archive_then_remove_profile(
    profile_id: str,
    profile: Mapping[str, Any],
    *,
    assert_inactive: Callable[[Mapping[str, Any]], None],
    terminal_records: Callable[[Mapping[str, Any]], Iterable[Mapping[str, Any]]],
    archive: Callable[[str, tuple[Mapping[str, Any], ...]], Any],
    remove: Callable[[], bool],
) -> bool:
    """Delegate the ordered archive/delete workflow to agent-library."""
    try:
        return _agent_library.archive_then_remove_profile(
            profile_id,
            profile,
            assert_inactive=assert_inactive,
            terminal_records=terminal_records,
            archive=archive,
            remove=remove,
        )
    except _agent_library.ProfileDeletionRejected as exc:
        raise RuntimeError(_BACH_ERRORS.get(exc.code, "worker_delete_execution_unconfirmed")) from exc
